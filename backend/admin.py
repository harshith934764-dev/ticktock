from fastapi import APIRouter,HTTPException,Request
from database import get_db
from videos import current_user_id
router=APIRouter(prefix="/api/admin",tags=["admin"])
def require_admin(request):
    uid=current_user_id(request)
    if not uid: raise HTTPException(401,"Login required")
    with get_db() as db: ok=db.execute("SELECT id FROM admins WHERE user_id=?",(uid,)).fetchone()
    if not ok: raise HTTPException(403,"Admin access required")
    return uid
@router.get("/dashboard")
def dashboard(request:Request):
    require_admin(request)
    with get_db() as db:
        return {"users":db.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],
                "videos":db.execute("SELECT COUNT(*) n FROM videos").fetchone()["n"],
                "open_reports":db.execute("SELECT COUNT(*) n FROM reports WHERE status='open'").fetchone()["n"],
                "views":db.execute("SELECT COUNT(*) n FROM video_views").fetchone()["n"]}
@router.get("/reports")
def reports(request:Request,status:str="open"):
    require_admin(request)
    with get_db() as db: rows=db.execute("SELECT * FROM reports WHERE status=? ORDER BY id DESC LIMIT 200",(status,)).fetchall()
    return [dict(r) for r in rows]
