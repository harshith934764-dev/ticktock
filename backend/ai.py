import re
from collections import Counter
from fastapi import APIRouter, HTTPException, Request
from database import get_db
from auth import serializer

router = APIRouter(prefix="/api/ai", tags=["ai"])

STOP = {
    "the","and","for","with","this","that","want","show","give","some","video",
    "videos","about","please","find","me","a","an","to","of","in","on","is","are",
    "my","i","you","it","from","more","best","new"
}

def uid_from_request(request: Request):
    h=request.headers.get("Authorization","")
    if not h.lower().startswith("bearer "): return None
    try:
        d=serializer.loads(h.split(" ",1)[1].strip(),max_age=60*60*24*30)
        return int(d["user_id"])
    except Exception:
        return None

def terms(text):
    words=re.findall(r"[a-zA-Z0-9_]{2,40}",text.lower())
    return list(dict.fromkeys(w for w in words if w not in STOP))[:8]

def record(uid, video_id, event, weight=1):
    with get_db() as db:
        db.execute(
            "INSERT INTO user_video_events(user_id,video_id,event,weight) VALUES(?,?,?,?)",
            (uid,str(video_id),event,float(weight))
        )

@router.get("/status")
def status():
    return {"success":True,"provider":"Tick Tock recommendation engine","mode":"local"}

@router.post("/event")
async def event(request: Request):
    uid=uid_from_request(request)
    if not uid: raise HTTPException(401,"Login required")
    data=await request.json()
    vid=data.get("video_id")
    ev=str(data.get("event","view")).lower()
    allowed={"view":1,"like":3,"comment":4,"share":5,"bookmark":4,"skip":-1}
    if vid is None or ev not in allowed: raise HTTPException(400,"Invalid AI event")
    record(uid,vid,ev,allowed[ev])
    return {"success":True}

@router.get("/recommendations")
def recommendations(request: Request, limit: int=20):
    uid=uid_from_request(request)
    limit=max(1,min(limit,50))
    with get_db() as db:
        if uid:
            rows=db.execute("""
                SELECT v.*, COALESCE(SUM(e.weight),0) AS interest_score
                FROM videos v
                LEFT JOIN user_video_events e
                  ON e.video_id=CAST(v.id AS TEXT) AND e.user_id=?
                WHERE v.privacy='public' OR v.privacy IS NULL
                GROUP BY v.id
                ORDER BY interest_score DESC, v.created_at DESC, v.id DESC
                LIMIT ?
            """,(uid,limit)).fetchall()
        else:
            rows=db.execute("""
                SELECT v.*, 0 AS interest_score
                FROM videos v
                WHERE v.privacy='public' OR v.privacy IS NULL
                ORDER BY v.created_at DESC,v.id DESC LIMIT ?
            """,(limit,)).fetchall()
    return {"success":True,"personalized":bool(uid),"videos":[dict(r) for r in rows]}

@router.post("/search")
async def ai_search(request: Request):
    uid=uid_from_request(request)
    if not uid: raise HTTPException(401,"Login required")
    data=await request.json()
    query=str(data.get("query","")).strip()[:300]
    if not query: raise HTTPException(400,"Type something to search.")
    ts=terms(query)
    clauses=[]; params=[]
    for t in ts or [query]:
        like=f"%{t}%"
        clauses.append("(lower(title) LIKE lower(?) OR lower(COALESCE(caption,'')) LIKE lower(?) OR lower(COALESCE(tags,'')) LIKE lower(?) OR lower(creator) LIKE lower(?))")
        params += [like]*4
    with get_db() as db:
        rows=db.execute(
            "SELECT id,title,url,creator,caption,tags FROM videos WHERE (privacy='public' OR privacy IS NULL) AND ("+" OR ".join(clauses)+") ORDER BY created_at DESC LIMIT 30",
            tuple(params)
        ).fetchall()
    return {"success":True,"query":query,"terms":ts or [query],"videos":[dict(r) for r in rows]}

@router.post("/comment-replies")
async def comment_replies(request: Request):
    uid=uid_from_request(request)
    if not uid: raise HTTPException(401,"Login required")
    data=await request.json()
    c=str(data.get("comment","")).strip()[:500]
    if not c: raise HTTPException(400,"Add a comment first.")
    return {"success":True,"replies":[f"Thanks for sharing!","I agree with you 😊","Interesting point!"]}

@router.post("/moderate-text")
async def moderate_text(request: Request):
    uid=uid_from_request(request)
    if not uid: raise HTTPException(401,"Login required")
    data=await request.json()
    text=str(data.get("text","")).strip()[:2000]
    if not text: raise HTTPException(400,"Text is empty.")
    risky=re.search(r"\b(threat|kill|bomb)\b",text,re.I)
    result={"risk":"high" if risky else "low","categories":["potential_threat"] if risky else [],"reason":"Automatic pre-check only.","action":"review" if risky else "allow"}
    return {"success":True,"result":result}
