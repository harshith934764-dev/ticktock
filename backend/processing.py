import shutil
from fastapi import APIRouter
router=APIRouter(prefix="/api/processing",tags=["processing"])
@router.get("/status")
def status():
    return {"ffmpeg_available":bool(shutil.which("ffmpeg")),
            "processor":"ffmpeg" if shutil.which("ffmpeg") else "not-installed"}
