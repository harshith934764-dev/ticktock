import os
ENV=os.getenv("ENV",os.getenv("APP_ENV","development")).strip().lower()
IS_PRODUCTION=ENV in {"production","prod"}
SECRET_KEY=os.getenv("SECRET_KEY","").strip()
if IS_PRODUCTION and len(SECRET_KEY)<32:
    raise RuntimeError("SECRET_KEY must be 32+ characters in production.")
FRONTEND_ORIGINS=[x.strip().rstrip("/") for x in os.getenv("FRONTEND_ORIGINS","http://localhost:3000").split(",") if x.strip()]
MAX_VIDEO_MB=int(os.getenv("MAX_VIDEO_MB","100"))
MAX_VIDEO_BYTES=MAX_VIDEO_MB*1024*1024
def is_production(): return IS_PRODUCTION
