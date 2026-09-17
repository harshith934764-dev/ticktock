from fastapi import APIRouter,HTTPException,Request
from database import get_db
from videos import current_user_id
router=APIRouter(prefix="/api/analytics",tags=["analytics"])
@router.get("/creator")
def creator(request:Request):
 uid=current_user_id(request)
 if not uid: raise HTTPException(401,"Login required")
 with get_db() as db:
  rows=db.execute("""SELECT v.id,v.title,v.created_at,(SELECT COUNT(*) FROM video_views x WHERE x.video_id=CAST(v.id AS TEXT)) views,(SELECT COUNT(*) FROM likes x WHERE x.video_id=CAST(v.id AS TEXT)) likes,(SELECT COUNT(*) FROM comments x WHERE x.video_id=CAST(v.id AS TEXT)) comments,(SELECT COUNT(*) FROM shares x WHERE x.video_id=CAST(v.id AS TEXT)) shares FROM videos v WHERE v.uploader_id=? ORDER BY v.id DESC LIMIT 100""",(uid,)).fetchall()
  followers=db.execute("SELECT COUNT(*) n FROM follows WHERE following_id=?",(uid,)).fetchone()["n"]
 totals={k:sum(float(r[k] or 0) for r in rows) for k in ("views","likes","comments","shares")}
 return {"followers":followers,"totals":totals,"videos":[dict(r) for r in rows]}
