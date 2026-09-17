import os
import sqlite3
from contextlib import contextmanager

DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
SQLITE_FILE = os.getenv('SQLITE_FILE', 'ticktock.db')

SCHEMA = [
'''CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    uid TEXT UNIQUE,
    gender TEXT,
    age INTEGER,
    photo TEXT,
    bio TEXT,
    location TEXT,
    profile_complete INTEGER DEFAULT 0,
    email_verified INTEGER DEFAULT 0,
    display_name TEXT,
    birth_date TEXT,
    friend_uid TEXT,
    google_id TEXT,
    is_ai_bot INTEGER DEFAULT 0,
    ai_bot_role TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''',
'''CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    creator TEXT NOT NULL,
    source TEXT NOT NULL,
    caption TEXT,
    tags TEXT,
    privacy TEXT DEFAULT 'public',
    uploader_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''',
'''CREATE TABLE IF NOT EXISTS likes (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    video_id TEXT NOT NULL,
    UNIQUE(user_id, video_id)
)''',
'''CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    video_id TEXT NOT NULL,
    comment TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''',
'''CREATE TABLE IF NOT EXISTS shares (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    video_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, video_id)
)''',
'''CREATE TABLE IF NOT EXISTS follows (
    id INTEGER PRIMARY KEY,
    follower_id INTEGER NOT NULL,
    following_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(follower_id, following_id)
)''',
'''CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    video_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, video_id)
)''',
'''CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    actor_id INTEGER,
    type TEXT NOT NULL,
    video_id TEXT,
    message TEXT NOT NULL,
    is_read INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''',
'''CREATE TABLE IF NOT EXISTS video_views (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    video_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''',
'''CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    reporter_id INTEGER NOT NULL,
    video_id TEXT,
    reported_user_id INTEGER,
    reason TEXT NOT NULL,
    status TEXT DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''',
'''CREATE TABLE IF NOT EXISTS blocks (
    id INTEGER PRIMARY KEY,
    blocker_id INTEGER NOT NULL,
    blocked_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(blocker_id, blocked_id)
)''',
'''CREATE TABLE IF NOT EXISTS friend_requests (
    id INTEGER PRIMARY KEY,
    sender_id INTEGER NOT NULL,
    receiver_id INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(sender_id, receiver_id)
)''',
'''CREATE TABLE IF NOT EXISTS friends (
    id INTEGER PRIMARY KEY,
    user1_id INTEGER NOT NULL,
    user2_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user1_id, user2_id)
)''',
'''CREATE TABLE IF NOT EXISTS diamond_wallets (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE,
    balance INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''',
'''CREATE TABLE IF NOT EXISTS diamond_transactions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    amount INTEGER NOT NULL,
    description TEXT,
    provider_order_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''',
'''CREATE TABLE IF NOT EXISTS gifts (
    id INTEGER PRIMARY KEY,
    sender_id INTEGER NOT NULL,
    receiver_id INTEGER NOT NULL,
    video_id TEXT,
    gift_name TEXT NOT NULL,
    diamonds INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''',
]

@contextmanager
def get_db():
    # Stage 1 intentionally uses SQLite for a zero-risk local start.
    # PostgreSQL/Supabase is wired in the next migration stage.
    db = sqlite3.connect(SQLITE_FILE)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def init_db():
    with get_db() as db:
        for statement in SCHEMA:
            db.execute(statement)

def fetch_all(query, params=()):
    with get_db() as db:
        return [dict(row) for row in db.execute(query, params).fetchall()]
