import re
from fastapi import APIRouter, HTTPException, Request
from database import get_db
from videos import current_user_id

router = APIRouter(prefix="/api/ai", tags=["ai"])
STOP={"the","and","for","with","this","that","from","have","your","you","are","was","video","reel","short","tick","tock"}
BAD_PATTERNS=[(r"\b(kill|murder|bomb|terrorist)\b",.75,"violent wording"),(r"\b(nude|porn|sex video|explicit)\b",.90,"sexual/explicit wording"),(r"\b(scamm?ed|fraud|phishing|steal password)\b",.65,"fraud/scam wording")]

def tokens(text): return [x for x in re.findall(r"[a-z0-9]{2,}",(text or "").lower()) if x not in STOP]
def moderation(text):
    hits=[]; sev=0.0
    for pat,score,reason in BAD_PATTERNS:
        if re.search(pat,(text or "")[:2000],re.I): hits.append(reason); sev=max(sev,score)
    return {"allowed":sev<.9,"severity":sev,"reasons":hits}

@router.get("/status")
def status(): return {"enabled":True,"engine":"Tick Tock local AI","paid_api_required":False}

@router.post("/event")
async def event(request:Request):
    uid=current_user_id(request)
    if not uid: raise HTTPException(401,"Login required")
    d=await request.json(); vid=str(d.get("video_id","")); ev=str(d.get("event","view"))
    if not vid: raise HTTPException(400,"video_id required")
    w={"view":1,"like":3,"comment":4,"share":5,"bookmark":4,"skip":-1}.get(ev,1)
    with get_db() as db: db.execute("INSERT INTO user_video_events(user_id,video_id,event,weight) VALUES(?,?,?,?)",(uid,vid,ev,w))
    return {"success":True,"weight":w}

@router.get("/recommendations")
def recommendations(request:Request,limit:int=20):
    uid=current_user_id(request); limit=max(1,min(limit,50))
    with get_db() as db:
        rows=db.execute("""SELECT v.id,v.title,v.url,v.creator,v.source,v.caption,v.tags,v.privacy,v.uploader_id,v.created_at,
        (SELECT COUNT(*) FROM likes l WHERE l.video_id=CAST(v.id AS TEXT)) likes,
        (SELECT COUNT(*) FROM comments c WHERE c.video_id=CAST(v.id AS TEXT)) comments,
        (SELECT COUNT(*) FROM shares s WHERE s.video_id=CAST(v.id AS TEXT)) shares,
        (SELECT COUNT(*) FROM video_views x WHERE x.video_id=CAST(v.id AS TEXT)) views
        FROM videos v WHERE v.privacy='public' OR v.privacy IS NULL ORDER BY v.created_at DESC,v.id DESC LIMIT 300""").fetchall()
        events=db.execute("SELECT video_id,event FROM user_video_events WHERE user_id=? ORDER BY id DESC LIMIT 500",(uid,)).fetchall() if uid else []
        interests=db.execute("SELECT interest,score FROM user_interests WHERE user_id=? ORDER BY score DESC LIMIT 30",(uid,)).fetchall() if uid else []
    seen={str(x["video_id"]) for x in events if x["event"] in ("view","like","comment","share","bookmark")}
    im={x["interest"]:float(x["score"]) for x in interests}; scored=[]
    for r in rows:
        text=" ".join(str(r[k] or "") for k in ("title","caption","tags","creator")).lower()
        match=sum(v for k,v in im.items() if k in text)
        score=match*8+r["likes"]*3+r["comments"]*4+r["shares"]*5+r["views"]*.15
        if str(r["id"]) in seen: score*=.45
        scored.append((score,dict(r)))
    scored.sort(key=lambda x:(x[0],str(x[1].get("created_at",""))),reverse=True)
    return [x[1] for x in scored[:limit]]

@router.get("/trending")
def trending(limit:int=20):
    limit=max(1,min(limit,50))
    with get_db() as db:
        rows=db.execute("""SELECT v.id,v.title,v.url,v.creator,v.caption,v.tags,v.created_at,
        (SELECT COUNT(*) FROM likes l WHERE l.video_id=CAST(v.id AS TEXT)) likes,
        (SELECT COUNT(*) FROM comments c WHERE c.video_id=CAST(v.id AS TEXT)) comments,
        (SELECT COUNT(*) FROM shares s WHERE s.video_id=CAST(v.id AS TEXT)) shares,
        (SELECT COUNT(*) FROM video_views x WHERE x.video_id=CAST(v.id AS TEXT)) views
        FROM videos v WHERE v.privacy='public' OR v.privacy IS NULL ORDER BY v.id DESC LIMIT 300""").fetchall()
    out=[]
    for r in rows: out.append((r["likes"]*3+r["comments"]*4+r["shares"]*6+r["views"]*.2,dict(r)))
    out.sort(key=lambda x:x[0],reverse=True)
    return [dict(r,trending_score=round(score,2)) for score,r in out[:limit]]

@router.get("/search")
def search(q:str="",limit:int=20):
    terms=tokens(q); limit=max(1,min(limit,50))
    if not terms:return []
    with get_db() as db: rows=db.execute("SELECT id,title,url,creator,caption,tags,privacy,created_at FROM videos WHERE privacy='public' OR privacy IS NULL ORDER BY id DESC LIMIT 500").fetchall()
    out=[]
    for r in rows:
        text=" ".join(str(r[k] or "") for k in ("title","creator","caption","tags")).lower(); score=sum(t in text for t in terms)
        if score: out.append((score,dict(r)))
    out.sort(key=lambda x:x[0],reverse=True); return [x[1] for x in out[:limit]]

@router.post("/moderate-text")
async def moderate_text(request:Request): return moderation(str((await request.json()).get("text","")))

@router.post("/interest")
async def add_interest(request:Request):
    uid=current_user_id(request)
    if not uid: raise HTTPException(401,"Login required")
    interest=str((await request.json()).get("interest","")).strip().lower()[:50]
    if not interest: raise HTTPException(400,"interest required")
    with get_db() as db:
        row=db.execute("SELECT id FROM user_interests WHERE user_id=? AND interest=?",(uid,interest)).fetchone()
        if row: db.execute("UPDATE user_interests SET score=score+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",(row["id"],))
        else: db.execute("INSERT INTO user_interests(user_id,interest,score) VALUES(?,?,1)",(uid,interest))
    return {"success":True,"interest":interest}

@router.get("/interests")
def interests(request:Request):
    uid=current_user_id(request)
    if not uid: raise HTTPException(401,"Login required")
    with get_db() as db: rows=db.execute("SELECT interest,ROUND(score,2) score FROM user_interests WHERE user_id=? ORDER BY score DESC LIMIT 50",(uid,)).fetchall()
    return [dict(r) for r in rows]
