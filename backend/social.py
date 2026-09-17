from fastapi import APIRouter, HTTPException, Request
from database import get_db
from auth import serializer

router = APIRouter(prefix="/api/social", tags=["social"])

def uid_from_request(request: Request):
    h = request.headers.get("Authorization", "")
    if not h.lower().startswith("bearer "):
        return None
    try:
        data = serializer.loads(h.split(" ", 1)[1].strip(), max_age=60*60*24*30)
        return int(data["user_id"])
    except Exception:
        return None

def require_uid(request: Request):
    uid = uid_from_request(request)
    if not uid:
        raise HTTPException(401, "Login required")
    return uid

@router.get("/profile/{username}")
def profile(username: str):
    with get_db() as db:
        u = db.execute("""
            SELECT id,uid,username,name,bio,photo,created_at
            FROM users WHERE lower(username)=lower(?)
        """, (username,)).fetchone()
        if not u:
            raise HTTPException(404, "User not found")
        followers = db.execute(
            "SELECT COUNT(*) n FROM follows WHERE following_id=?", (u["id"],)
        ).fetchone()["n"]
        following = db.execute(
            "SELECT COUNT(*) n FROM follows WHERE follower_id=?", (u["id"],)
        ).fetchone()["n"]
    result = dict(u)
    result["followers"] = followers
    result["following"] = following
    return result

@router.post("/follow/{user_id}")
def follow(user_id: int, request: Request):
    me = require_uid(request)
    if me == user_id:
        raise HTTPException(400, "You cannot follow yourself")
    with get_db() as db:
        target = db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, "User not found")
        blocked = db.execute("""
            SELECT 1 FROM blocks
            WHERE (blocker_id=? AND blocked_id=?)
               OR (blocker_id=? AND blocked_id=?)
        """, (me, user_id, user_id, me)).fetchone()
        if blocked:
            raise HTTPException(403, "Follow unavailable")
        exists = db.execute(
            "SELECT id FROM follows WHERE follower_id=? AND following_id=?",
            (me, user_id)
        ).fetchone()
        if exists:
            db.execute("DELETE FROM follows WHERE id=?", (exists["id"],))
            following = False
        else:
            db.execute(
                "INSERT OR IGNORE INTO follows(follower_id,following_id) VALUES(?,?)",
                (me, user_id)
            )
            following = True
    return {"success": True, "following": following}

@router.get("/followers/{user_id}")
def followers(user_id: int):
    with get_db() as db:
        rows = db.execute("""
            SELECT u.id,u.uid,u.username,u.name,u.photo
            FROM follows f JOIN users u ON u.id=f.follower_id
            WHERE f.following_id=? ORDER BY f.id DESC
        """, (user_id,)).fetchall()
    return [dict(r) for r in rows]

@router.get("/following/{user_id}")
def following(user_id: int):
    with get_db() as db:
        rows = db.execute("""
            SELECT u.id,u.uid,u.username,u.name,u.photo
            FROM follows f JOIN users u ON u.id=f.following_id
            WHERE f.follower_id=? ORDER BY f.id DESC
        """, (user_id,)).fetchall()
    return [dict(r) for r in rows]

@router.post("/friend-request/{user_id}")
def friend_request(user_id: int, request: Request):
    me = require_uid(request)
    if me == user_id:
        raise HTTPException(400, "Invalid friend request")
    with get_db() as db:
        target = db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, "User not found")
        # Support common schema variants used by Tick Tock.
        cols = [r["name"] for r in db.execute("PRAGMA table_info(friend_requests)").fetchall()]
        if not cols:
            raise HTTPException(501, "Friend requests table is not available")
        if "sender_id" in cols and "receiver_id" in cols:
            existing = db.execute(
                "SELECT id,status FROM friend_requests WHERE sender_id=? AND receiver_id=?",
                (me, user_id)
            ).fetchone()
            if existing:
                return {"success": True, "status": existing["status"]}
            db.execute(
                "INSERT INTO friend_requests(sender_id,receiver_id,status) VALUES(?,?,?)",
                (me, user_id, "pending")
            )
        elif "from_user_id" in cols and "to_user_id" in cols:
            existing = db.execute(
                "SELECT id,status FROM friend_requests WHERE from_user_id=? AND to_user_id=?",
                (me, user_id)
            ).fetchone()
            if existing:
                return {"success": True, "status": existing["status"]}
            db.execute(
                "INSERT INTO friend_requests(from_user_id,to_user_id,status) VALUES(?,?,?)",
                (me, user_id, "pending")
            )
        else:
            raise HTTPException(501, "Unsupported friend request schema")
    return {"success": True, "status": "pending"}

@router.post("/friend-request/{request_id}/accept")
def accept_friend_request(request_id: int, request: Request):
    me = require_uid(request)
    with get_db() as db:
        cols = [r["name"] for r in db.execute("PRAGMA table_info(friend_requests)").fetchall()]
        if "receiver_id" in cols:
            row = db.execute(
                "SELECT * FROM friend_requests WHERE id=? AND receiver_id=?",
                (request_id, me)
            ).fetchone()
        elif "to_user_id" in cols:
            row = db.execute(
                "SELECT * FROM friend_requests WHERE id=? AND to_user_id=?",
                (request_id, me)
            ).fetchone()
        else:
            raise HTTPException(501, "Unsupported friend request schema")
        if not row:
            raise HTTPException(404, "Friend request not found")
        db.execute("UPDATE friend_requests SET status='accepted' WHERE id=?", (request_id,))
    return {"success": True, "status": "accepted"}

@router.get("/friend-requests")
def friend_requests(request: Request):
    me = require_uid(request)
    with get_db() as db:
        cols = [r["name"] for r in db.execute("PRAGMA table_info(friend_requests)").fetchall()]
        if "receiver_id" in cols:
            rows = db.execute("""
                SELECT fr.id,fr.status,fr.sender_id AS user_id,
                       u.username,u.name,u.photo
                FROM friend_requests fr JOIN users u ON u.id=fr.sender_id
                WHERE fr.receiver_id=? ORDER BY fr.id DESC
            """, (me,)).fetchall()
        elif "to_user_id" in cols:
            rows = db.execute("""
                SELECT fr.id,fr.status,fr.from_user_id AS user_id,
                       u.username,u.name,u.photo
                FROM friend_requests fr JOIN users u ON u.id=fr.from_user_id
                WHERE fr.to_user_id=? ORDER BY fr.id DESC
            """, (me,)).fetchall()
        else:
            raise HTTPException(501, "Unsupported friend request schema")
    return [dict(r) for r in rows]

@router.post("/block/{user_id}")
def block(user_id: int, request: Request):
    me = require_uid(request)
    if me == user_id:
        raise HTTPException(400, "Invalid block")
    with get_db() as db:
        target = db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, "User not found")
        db.execute(
            "INSERT OR IGNORE INTO blocks(blocker_id,blocked_id) VALUES(?,?)",
            (me, user_id)
        )
        db.execute(
            "DELETE FROM follows WHERE (follower_id=? AND following_id=?) OR (follower_id=? AND following_id=?)",
            (me, user_id, user_id, me)
        )
    return {"success": True, "blocked": True}

@router.delete("/block/{user_id}")
def unblock(user_id: int, request: Request):
    me = require_uid(request)
    with get_db() as db:
        db.execute(
            "DELETE FROM blocks WHERE blocker_id=? AND blocked_id=?",
            (me, user_id)
        )
    return {"success": True, "blocked": False}

@router.get("/notifications")
def notifications(request: Request):
    me = require_uid(request)
    with get_db() as db:
        # Return safely if the existing notification table uses a different schema.
        cols = [r["name"] for r in db.execute("PRAGMA table_info(notifications)").fetchall()]
        if not cols:
            return []
        rows = db.execute(
            "SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100",
            (me,)
        ).fetchall() if "user_id" in cols else []
    return [dict(r) for r in rows]
