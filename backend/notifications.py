from fastapi import APIRouter,HTTPException,Request
from database import get_db
from videos import current_user_id
router=APIRouter(prefix="/api/notifications",tags=["notifications"])
@router.get("")
def list_notifications(request:Request,limit:int=30):
    uid=current_user_id(request)
    if not uid: raise HTTPException(401,"Login required")
    with get_db() as db:
        rows=db.execute("SELECT id,actor_id,type,video_id,message,is_read,created_at FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT ?",(uid,max(1,min(limit,100)))).fetchall()
    return [dict(r) for r in rows]
@router.post("/read-all")
def read_all(request:Request):
    uid=current_user_id(request)
    if not uid: raise HTTPException(401,"Login required")
    with get_db() as db: db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?",(uid,))
    return {"success":True}
