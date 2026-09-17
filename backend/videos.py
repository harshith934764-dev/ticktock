import os
import secrets
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from database import get_db
from auth import serializer
from config import MAX_VIDEO_BYTES
from storage import upload_bytes

router = APIRouter(prefix="/api/videos", tags=["videos"])
UPLOAD_DIR = Path(os.getenv("VIDEO_UPLOAD_DIR", "uploads/videos"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED = {"mp4", "webm", "mov", "m4v"}

def current_user_id(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    try:
        data = serializer.loads(token, max_age=60 * 60 * 24 * 30)
        return int(data["user_id"])
    except Exception:
        return None

def video_id_value(value):
    return str(value)

@router.get("")
def feed(limit: int = 20):
    limit = max(1, min(limit, 100))
    with get_db() as db:
        rows = db.execute("""
            SELECT v.id,v.title,v.url,v.creator,v.source,v.caption,v.tags,v.privacy,
                   v.uploader_id,v.created_at,
                   (SELECT COUNT(*) FROM likes l WHERE l.video_id=CAST(v.id AS TEXT)) AS likes,
                   (SELECT COUNT(*) FROM comments c WHERE c.video_id=CAST(v.id AS TEXT)) AS comments,
                   (SELECT COUNT(*) FROM shares s WHERE s.video_id=CAST(v.id AS TEXT)) AS shares,
                   (SELECT COUNT(*) FROM video_views vv WHERE vv.video_id=CAST(v.id AS TEXT)) AS views
            FROM videos v
            WHERE v.privacy='public' OR v.privacy IS NULL
            ORDER BY v.created_at DESC, v.id DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]

@router.get("/{video_id}")
def get_video(video_id: str):
    with get_db() as db:
        row = db.execute("""
            SELECT v.id,v.title,v.url,v.creator,v.source,v.caption,v.tags,v.privacy,
                   v.uploader_id,v.created_at,
                   (SELECT COUNT(*) FROM likes l WHERE l.video_id=?) AS likes,
                   (SELECT COUNT(*) FROM comments c WHERE c.video_id=?) AS comments,
                   (SELECT COUNT(*) FROM shares s WHERE s.video_id=?) AS shares,
                   (SELECT COUNT(*) FROM video_views vv WHERE vv.video_id=?) AS views
            FROM videos v
            WHERE CAST(v.id AS TEXT)=?
        """, (video_id, video_id, video_id, video_id, video_id)).fetchone()
    if not row:
        raise HTTPException(404, "Video not found")
    return dict(row)

@router.post("/{video_id}/like")
def like(video_id: str, request: Request):
    uid = current_user_id(request)
    if not uid:
        raise HTTPException(401, "Login required")
    with get_db() as db:
        existing = db.execute(
            "SELECT id FROM likes WHERE user_id=? AND video_id=?",
            (uid, video_id)
        ).fetchone()
        if existing:
            db.execute("DELETE FROM likes WHERE id=?", (existing["id"],))
            liked = False
        else:
            db.execute(
                "INSERT OR IGNORE INTO likes(user_id,video_id) VALUES(?,?)",
                (uid, video_id)
            )
            db.execute(
                "INSERT INTO user_video_events(user_id,video_id,event,weight) VALUES(?,?,?,?)",
                (uid, video_id, "like", 3)
            )
            liked = True
        count = db.execute(
            "SELECT COUNT(*) AS n FROM likes WHERE video_id=?", (video_id,)
        ).fetchone()["n"]
    return {"success": True, "liked": liked, "count": count}

@router.post("/{video_id}/view")
def view(video_id: str, request: Request):
    uid = current_user_id(request)
    with get_db() as db:
        exists = db.execute(
            "SELECT id FROM videos WHERE CAST(id AS TEXT)=?", (video_id,)
        ).fetchone()
        if not exists:
            raise HTTPException(404, "Video not found")
        db.execute(
            "INSERT INTO video_views(user_id,video_id) VALUES(?,?)",
            (uid, video_id)
        )
        if uid:
            db.execute(
                "INSERT INTO user_video_events(user_id,video_id,event,weight) VALUES(?,?,?,?)",
                (uid, video_id, "view", 1)
            )
        count = db.execute(
            "SELECT COUNT(*) AS n FROM video_views WHERE video_id=?", (video_id,)
        ).fetchone()["n"]
    return {"success": True, "views": count}

@router.post("/{video_id}/share")
def share(video_id: str, request: Request):
    uid = current_user_id(request)
    if not uid:
        raise HTTPException(401, "Login required")
    with get_db() as db:
        db.execute(
            "INSERT OR IGNORE INTO shares(user_id,video_id) VALUES(?,?)",
            (uid, video_id)
        )
        count = db.execute(
            "SELECT COUNT(*) AS n FROM shares WHERE video_id=?", (video_id,)
        ).fetchone()["n"]
    return {"success": True, "count": count}

@router.get("/{video_id}/comments")
def comments(video_id: str):
    with get_db() as db:
        rows = db.execute("""
            SELECT c.id,c.comment,c.created_at,u.username,u.uid,u.photo
            FROM comments c
            JOIN users u ON u.id=c.user_id
            WHERE c.video_id=?
            ORDER BY c.id DESC
        """, (video_id,)).fetchall()
    return [dict(r) for r in rows]

@router.post("/{video_id}/comments")
async def add_comment(video_id: str, request: Request):
    uid = current_user_id(request)
    if not uid:
        raise HTTPException(401, "Login required")
    data = await request.json()
    comment = str(data.get("comment", "")).strip()[:500]
    if not comment:
        raise HTTPException(400, "Comment cannot be empty")
    with get_db() as db:
        db.execute(
            "INSERT INTO comments(user_id,video_id,comment) VALUES(?,?,?)",
            (uid, video_id, comment)
        )
        row = db.execute(
            "SELECT username FROM users WHERE id=?", (uid,)
        ).fetchone()
    return {"success": True, "comment": comment, "username": row["username"]}

@router.post("/{video_id}/bookmark")
def bookmark(video_id: str, request: Request):
    uid = current_user_id(request)
    if not uid:
        raise HTTPException(401, "Login required")
    with get_db() as db:
        existing = db.execute(
            "SELECT id FROM bookmarks WHERE user_id=? AND video_id=?",
            (uid, video_id)
        ).fetchone()
        if existing:
            db.execute("DELETE FROM bookmarks WHERE id=?", (existing["id"],))
            saved = False
        else:
            db.execute(
                "INSERT OR IGNORE INTO bookmarks(user_id,video_id) VALUES(?,?)",
                (uid, video_id)
            )
            saved = True
    return {"success": True, "saved": saved}

@router.post("/upload")
async def upload_video(
    request: Request,
    video: UploadFile = File(...),
    caption: str = Form(""),
    tags: str = Form(""),
    privacy: str = Form("public"),
):
    uid = current_user_id(request)
    if not uid:
        raise HTTPException(401, "Login required")

    ext = Path(video.filename or "").suffix.lower().lstrip(".")
    if ext not in ALLOWED:
        raise HTTPException(400, "Only MP4, WEBM, MOV and M4V are allowed")

    with get_db() as db:
        user = db.execute(
            "SELECT id,username FROM users WHERE id=?", (uid,)
        ).fetchone()
    if not user:
        raise HTTPException(401, "User not found")

    # Read in bounded chunks so an oversized upload is rejected before storage.
    chunks = []
    total = 0
    while True:
        chunk = await video.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_VIDEO_BYTES:
            raise HTTPException(413, f"Video is too large. Maximum is {MAX_VIDEO_BYTES // (1024 * 1024)} MB.")
        chunks.append(chunk)

    try:
        media_url, storage_key = upload_bytes(b"".join(chunks), ext)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))

    privacy = privacy if privacy in {"public", "private"} else "public"
    title = storage_key

    with get_db() as db:
        cur = db.execute("""
            INSERT INTO videos
            (title,url,creator,source,caption,tags,privacy,uploader_id)
            VALUES(?,?,?,?,?,?,?,?)
        """, (
            title, media_url, user["username"], "fastapi_upload",
            caption.strip()[:500], tags.strip()[:500], privacy, uid
        ))
        video_id = cur.lastrowid

    return {
        "success": True,
        "video_id": video_id,
        "url": media_url,
        "title": title,
        "creator": user["username"],
        "caption": caption.strip()[:500],
        "tags": tags.strip()[:500],
        "privacy": privacy,
    }
