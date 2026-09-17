import os,secrets
from pathlib import Path
import requests
BUCKET=os.getenv("SUPABASE_STORAGE_BUCKET","videos").strip()
SUPABASE_URL=os.getenv("SUPABASE_URL","").strip().rstrip("/")
SUPABASE_SERVICE_KEY=os.getenv("SUPABASE_SERVICE_ROLE_KEY","").strip()
LOCAL_DIR=Path(os.getenv("VIDEO_UPLOAD_DIR","uploads/videos")); LOCAL_DIR.mkdir(parents=True,exist_ok=True)
def cloud_enabled(): return bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)
def upload_bytes(data:bytes, extension:str):
    ext=extension.lower().lstrip("."); key=f"{secrets.token_hex(16)}.{ext}"
    if cloud_enabled():
        r=requests.post(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{key}",
            headers={"Authorization":f"Bearer {SUPABASE_SERVICE_KEY}","apikey":SUPABASE_SERVICE_KEY,
                     "Content-Type":"application/octet-stream","x-upsert":"false"},data=data,timeout=120)
        if not r.ok: raise RuntimeError(f"Cloud video upload failed ({r.status_code}).")
        return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{key}",key
    (LOCAL_DIR/key).write_bytes(data)
    return f"/uploads/videos/{key}",key
