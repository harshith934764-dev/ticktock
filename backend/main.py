import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from database import init_db
from users import router as users_router
from videos import router as videos_router
from social import router as social_router
from auth import router as auth_router
from ai import router as ai_router
from analytics import router as analytics_router
from feed import router as feed_router
from notifications import router as notifications_router
from moderation import router as moderation_router
from admin import router as admin_router
from payments import router as payments_router
from processing import router as processing_router
from realtime import router as realtime_router
from config import FRONTEND_ORIGINS, is_production

app = FastAPI(
    title="Tick Tock API",
    version="1.1.0",
    docs_url=None if is_production() else "/docs",
    redoc_url=None if is_production() else "/redoc",
)

app.include_router(users_router)
app.include_router(videos_router)
app.include_router(social_router)
app.include_router(auth_router)
app.include_router(ai_router)
app.include_router(analytics_router)
app.include_router(feed_router)
app.include_router(notifications_router)
app.include_router(moderation_router)
app.include_router(admin_router)
app.include_router(payments_router)
app.include_router(processing_router)
app.include_router(realtime_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if is_production():
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    # Never leak stack traces or secrets to clients.
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error."},
    )

@app.on_event("startup")
def startup():
    init_db()

@app.get("/")
def root():
    return {"app": "Tick Tock", "backend": "FastAPI", "status": "running"}

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "ticktock-fastapi"}

@app.get("/api")
def api_info():
    return {
        "name": "Tick Tock API",
        "version": "1.1.0",
        "status": "ready",
        "routes": ["/healthz", "/api/users", "/api/videos"],
    }
