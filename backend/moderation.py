from fastapi import APIRouter,HTTPException,Request
from database import get_db
from videos import current_user_id
router=APIRouter(prefix="/api/moderation",tags=["moderation"])
@router.post("/report")
async def report(request:Request):
    uid=current_user_id(request)
    if not uid: raise HTTPException(401,"Login required")
    d=await request.json(); reason=str(d.get("reason","")).strip()[:300]
    vid=d.get("video_id"); rid=d.get("reported_user_id")
    if not reason or (not vid and not rid): raise HTTPException(400,"Provide a reason and a video or user.")
    with get_db() as db:
        db.execute("INSERT INTO reports(reporter_id,video_id,reported_user_id,reason,status) VALUES(?,?,?,?,?)",
                   (uid,str(vid) if vid else None,int(rid) if rid else None,reason,"open"))
    return {"success":True,"status":"open"}
