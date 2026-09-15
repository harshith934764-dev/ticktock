from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    send_from_directory
)

import sqlite3
import os
import random
import string
import re
import requests
import time
import hashlib
import secrets
import hmac
import datetime
import shutil

from email.message import EmailMessage
import smtplib

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix


app = Flask(
    __name__,
    template_folder="templates"
)

# Render sits behind a reverse proxy. Trust the forwarded HTTPS scheme so
# OAuth callback URLs are generated as https://... instead of http://....
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "tick-tock-secret-key"
)
# Keep uploads bounded so one request cannot consume excessive server memory/storage.
app.config["MAX_CONTENT_LENGTH"] = 80 * 1024 * 1024


# =========================================================
# EMAIL OTP SETTINGS
# =========================================================

OTP_EXPIRY_SECONDS = 3 * 60
OTP_MAX_ATTEMPTS = 3
OTP_LOCK_SECONDS = 5 * 60
TRUSTED_DEVICE_DAYS = 30
TRUSTED_COOKIE = "tt_trusted_device"
FORCE_OTP_COOKIE = "tt_force_otp"

# Google Sign-In (OAuth 2.0)
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "").strip()
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"




def generate_otp():
    return str(
        random.randint(100000, 999999)
    )


def hash_otp(otp):
    return hashlib.sha256(
        otp.encode("utf-8")
    ).hexdigest()


def send_otp_email(to_email, otp):
    """
    Send OTP through Resend's HTTPS Email API.

    Render Free blocks outbound SMTP ports 25/465/587, so HTTP email
    delivery is used first. SMTP remains as a fallback for local/paid
    environments where SMTP is available.
    """
    resend_api_key = os.environ.get("RESEND_API_KEY", "").strip()
    email_from = os.environ.get(
        "EMAIL_FROM",
        "onboarding@resend.dev"
    ).strip()

    subject = "Tick Tock Login OTP"

    text_body = f"""Hello,

Your Tick Tock login OTP is:

{otp}

This OTP expires in 3 minutes.

If you did not request this OTP, please ignore this email.

Tick Tock ❤️
"""

    html_body = f"""
    <div style="font-family:Arial,sans-serif;line-height:1.6">
      <h2>🎵 Tick Tock</h2>
      <p>Your login OTP is:</p>
      <div style="font-size:32px;font-weight:700;letter-spacing:8px;
                  padding:16px 20px;background:#f3f4ff;border-radius:12px;
                  display:inline-block">{otp}</div>
      <p>This OTP expires in <b>3 minutes</b>.</p>
      <p>If you did not request this OTP, please ignore this email.</p>
      <p>Tick Tock ❤️</p>
    </div>
    """

    # Preferred method on Render: HTTPS API.
    if resend_api_key:
        try:
            response = requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": email_from,
                    "to": [to_email],
                    "subject": subject,
                    "text": text_body,
                    "html": html_body,
                },
                timeout=20,
            )

            if response.ok:
                print("OTP sent successfully with Resend to:", to_email)
                return True

            print(
                "Resend OTP error:",
                response.status_code,
                response.text[:1000],
            )
            return False

        except Exception as error:
            print("Resend OTP connection error:", error)
            return False

    # Local/paid-Render fallback. Do not rely on this on Render Free.
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    try:
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    except (TypeError, ValueError):
        smtp_port = 587

    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")

    if not smtp_user or not smtp_password:
        print(
            "Email service is not configured. "
            "Set RESEND_API_KEY in Render Environment Variables."
        )
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp_user
    message["To"] = to_email
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(
            smtp_host,
            smtp_port,
            timeout=20
        ) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(message)

        print("OTP sent successfully with SMTP to:", to_email)
        return True

    except Exception as error:
        print("SMTP OTP error:", error)
        return False


def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _issue_trusted_device(user_id):
    token = secrets.token_urlsafe(48)
    token_hash = _hash_token(token)
    db = get_db()
    db.execute(
        "UPDATE users SET trusted_token_hash=?, trusted_token_expires=? WHERE id=?",
        (token_hash, time.time() + TRUSTED_DEVICE_DAYS * 86400, user_id),
    )
    db.commit()
    db.close()
    return token


def _trusted_user(email):
    token = request.cookies.get(TRUSTED_COOKIE, "").strip()
    if not token:
        return None
    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE lower(username)=? AND trusted_token_hash=? AND trusted_token_expires>?",
        (email, _hash_token(token), time.time()),
    ).fetchone()
    db.close()
    return user


def _start_user_session(user):
    session.clear()
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["uid"] = user["uid"]


def _set_trusted_cookie(response, token):
    response.set_cookie(
        TRUSTED_COOKIE, token, max_age=TRUSTED_DEVICE_DAYS * 86400,
        httponly=True, secure=True, samesite="Lax"
    )
    response.set_cookie(FORCE_OTP_COOKIE, "", max_age=0, httponly=True, secure=True, samesite="Lax")
    return response


def clear_otp_session():

    session.pop(
        "otp_hash",
        None
    )

    session.pop(
        "otp_expires",
        None
    )

    session.pop(
        "otp_attempts",
        None
    )

    session.pop(
        "otp_locked_until",
        None
    )

    session.pop(
        "otp_user_id",
        None
    )

    session.pop(
        "otp_email",
        None
    )


# =========================================================
# DATABASE
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Render Postgres is used when DATABASE_URL is present.
# SQLite remains available for local development only.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)

DATA_DIR = os.environ.get("TICKTOCK_DATA_DIR", BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)

DB_FILE = os.path.join(DATA_DIR, "ticktock.db")
UPLOAD_FOLDER = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 80 * 1024 * 1024

_pg_pool = None

if USE_POSTGRES:
    try:
        from psycopg_pool import ConnectionPool
        from psycopg.rows import dict_row

        _pg_pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=int(os.environ.get("DATABASE_POOL_MIN", "1")),
            max_size=int(os.environ.get("DATABASE_POOL_MAX", "10")),
            timeout=10,
            kwargs={"row_factory": dict_row},
            open=True,
        )
    except Exception as error:
        raise RuntimeError(
            "PostgreSQL is configured but psycopg is unavailable or the database URL is invalid: " + str(error)
        )


def _pg_sql(sql):
    """Translate the app's existing SQLite-style placeholders to psycopg."""
    sql = sql.replace("?", "%s")
    sql = re.sub(
        r"INSERT\s+OR\s+IGNORE\s+INTO",
        "INSERT INTO",
        sql,
        flags=re.IGNORECASE,
    )
    # PostgreSQL can safely ignore duplicate rows when the statement has a UNIQUE constraint.
    if re.search(r"INSERT INTO", sql, flags=re.IGNORECASE) and "ON CONFLICT" not in sql.upper():
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return sql


class _PostgresDB:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=()):
        return self.connection.execute(_pg_sql(sql), params)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        if _pg_pool is not None:
            try:
                _pg_pool.putconn(self.connection)
                return
            except Exception:
                pass
        self.connection.close()


def get_db():
    if USE_POSTGRES:
        return _PostgresDB(_pg_pool.getconn())

    db = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA busy_timeout=30000")
    return db


def column_exists(db, table, column):
    if USE_POSTGRES:
        row = db.execute(
            """
            SELECT 1 AS found
            FROM information_schema.columns
            WHERE table_schema='public'
              AND table_name=?
              AND column_name=?
            LIMIT 1
            """,
            (table, column),
        ).fetchone()
        return bool(row)

    columns = db.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in columns)


def add_column_if_missing(db, table, column, definition):
    if not column_exists(db, table, column):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def create_uid(db):
    while True:
        uid = "TTK-" + "".join(
            random.choices(string.ascii_uppercase + string.digits, k=10)
        )
        found = db.execute(
            "SELECT id FROM users WHERE uid=?", (uid,)
        ).fetchone()
        if not found:
            return uid


def create_friend_uid(db):
    """Generate a simple 8-digit friend UID while preserving the legacy uid."""
    while True:
        code = str(random.randint(10000000, 99999999))
        found = db.execute("SELECT id FROM users WHERE friend_uid=?", (code,)).fetchone()
        if not found:
            return code


def _init_sqlite():
    # Keep the existing local-development database schema.
    db = get_db()
    db.executescript if hasattr(db, "executescript") else None
    db.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        uid TEXT UNIQUE,
        gender TEXT,
        age INTEGER,
        photo TEXT,
        bio TEXT,
        location TEXT,
        profile_complete INTEGER DEFAULT 0,
        display_name TEXT,
        birth_date TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    for c, d in [
        ("uid", "TEXT"), ("gender", "TEXT"), ("age", "INTEGER"),
        ("photo", "TEXT"), ("bio", "TEXT"), ("location", "TEXT"),
        ("profile_complete", "INTEGER DEFAULT 0"),
        ("email_verified", "INTEGER DEFAULT 0"),
        ("trusted_token_hash", "TEXT"),
        ("trusted_token_expires", "REAL"),
        ("display_name", "TEXT"),
        ("birth_date", "TEXT"),
        ("friend_uid", "TEXT"),
        ("google_id", "TEXT"),
    ]:
        add_column_if_missing(db, "users", c, d)

    users_without_uid = db.execute(
        "SELECT id FROM users WHERE uid IS NULL OR uid=''"
    ).fetchall()
    for user in users_without_uid:
        db.execute("UPDATE users SET uid=? WHERE id=?", (create_uid(db), user["id"]))

    users_without_friend_uid = db.execute("SELECT id FROM users WHERE friend_uid IS NULL OR friend_uid=''").fetchall()
    for user in users_without_friend_uid:
        db.execute("UPDATE users SET friend_uid=? WHERE id=?", (create_friend_uid(db), user["id"]))

    db.execute("""CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        url TEXT NOT NULL,
        creator TEXT NOT NULL,
        source TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        video_id TEXT NOT NULL,
        UNIQUE(user_id, video_id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        video_id TEXT NOT NULL,
        comment TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS shares (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        video_id TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, video_id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS friend_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(sender_id, receiver_id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS friends (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user1_id INTEGER NOT NULL,
        user2_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user1_id, user2_id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS blocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        blocker_id INTEGER NOT NULL,
        blocked_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(blocker_id, blocked_id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS follows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        follower_id INTEGER NOT NULL,
        following_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(follower_id, following_id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS diamond_wallets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE,
        balance INTEGER NOT NULL DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS diamond_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        amount INTEGER NOT NULL,
        description TEXT,
        provider_order_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS gifts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        video_id TEXT,
        gift_name TEXT NOT NULL,
        diamonds INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS bookmarks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, video_id TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id, video_id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, actor_id INTEGER,
        type TEXT NOT NULL, video_id TEXT, message TEXT NOT NULL, is_read INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS video_views (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, video_id TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id INTEGER NOT NULL, video_id TEXT,
        reported_user_id INTEGER, reason TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    for c, d in [
        ("caption", "TEXT"), ("tags", "TEXT"),
        ("privacy", "TEXT DEFAULT 'public'"), ("uploader_id", "INTEGER"),
        ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ]:
        add_column_if_missing(db, "videos", c, d)
    db.execute("""UPDATE videos SET uploader_id=(
        SELECT users.id FROM users WHERE users.username=videos.creator
    ) WHERE uploader_id IS NULL""")
    db.execute("UPDATE videos SET privacy='public' WHERE privacy IS NULL OR privacy='' ")
    db.commit()
    db.close()


def _init_postgres():
    db = get_db()
    statements = [
        """CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
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
            trusted_token_hash TEXT,
            trusted_token_expires DOUBLE PRECISION,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS videos (
            id BIGSERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            creator TEXT NOT NULL,
            source TEXT NOT NULL,
            caption TEXT,
            tags TEXT,
            privacy TEXT DEFAULT 'public',
            uploader_id BIGINT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS likes (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            video_id TEXT NOT NULL,
            UNIQUE(user_id, video_id)
        )""",
        """CREATE TABLE IF NOT EXISTS comments (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            video_id TEXT NOT NULL,
            comment TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS shares (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            video_id TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, video_id)
        )""",
        """CREATE TABLE IF NOT EXISTS friend_requests (
            id BIGSERIAL PRIMARY KEY,
            sender_id BIGINT NOT NULL,
            receiver_id BIGINT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(sender_id, receiver_id)
        )""",
        """CREATE TABLE IF NOT EXISTS friends (
            id BIGSERIAL PRIMARY KEY,
            user1_id BIGINT NOT NULL,
            user2_id BIGINT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user1_id, user2_id)
        )""",
        """CREATE TABLE IF NOT EXISTS blocks (
            id BIGSERIAL PRIMARY KEY,
            blocker_id BIGINT NOT NULL,
            blocked_id BIGINT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(blocker_id, blocked_id)
        )""",
        """CREATE TABLE IF NOT EXISTS follows (
            id BIGSERIAL PRIMARY KEY,
            follower_id BIGINT NOT NULL,
            following_id BIGINT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(follower_id, following_id)
        )""",
        """CREATE TABLE IF NOT EXISTS diamond_wallets (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT UNIQUE NOT NULL,
            balance BIGINT NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS diamond_transactions (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            type TEXT NOT NULL,
            amount BIGINT NOT NULL,
            description TEXT,
            provider_order_id TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS gifts (
            id BIGSERIAL PRIMARY KEY,
            sender_id BIGINT NOT NULL,
            receiver_id BIGINT NOT NULL,
            video_id TEXT,
            gift_name TEXT NOT NULL,
            diamonds BIGINT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS bookmarks (
            id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, video_id TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id, video_id)
        )""",
        """CREATE TABLE IF NOT EXISTS notifications (
            id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, actor_id BIGINT, type TEXT NOT NULL,
            video_id TEXT, message TEXT NOT NULL, is_read INTEGER DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS video_views (
            id BIGSERIAL PRIMARY KEY, user_id BIGINT, video_id TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS reports (
            id BIGSERIAL PRIMARY KEY, reporter_id BIGINT NOT NULL, video_id TEXT,
            reported_user_id BIGINT, reason TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )""",
    ]
    for statement in statements:
        db.execute(statement)

    # Safe schema upgrades for existing PostgreSQL databases.
    for c, d in [
        ("email_verified", "INTEGER DEFAULT 0"),
        ("trusted_token_hash", "TEXT"),
        ("trusted_token_expires", "DOUBLE PRECISION"),
        ("display_name", "TEXT"),
        ("birth_date", "DATE"),
        ("friend_uid", "TEXT"),
        ("google_id", "TEXT"),
    ]:
        add_column_if_missing(db, "users", c, d)

    # Fast indexes for the feed and social graph.
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_videos_feed ON videos (created_at DESC, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_videos_public ON videos (privacy, created_at DESC, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_videos_uploader ON videos (uploader_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_likes_video ON likes (video_id)",
        "CREATE INDEX IF NOT EXISTS idx_comments_video ON comments (video_id, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_shares_video ON shares (video_id)",
        "CREATE INDEX IF NOT EXISTS idx_follows_follower ON follows (follower_id, following_id)",
        "CREATE INDEX IF NOT EXISTS idx_follows_following ON follows (following_id, follower_id)",
        "CREATE INDEX IF NOT EXISTS idx_friend_requests_receiver ON friend_requests (receiver_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_friends_user1 ON friends (user1_id, user2_id)",
        "CREATE INDEX IF NOT EXISTS idx_friends_user2 ON friends (user2_id, user1_id)",
        "CREATE INDEX IF NOT EXISTS idx_blocks_blocker ON blocks (blocker_id, blocked_id)",
        "CREATE INDEX IF NOT EXISTS idx_blocks_blocked ON blocks (blocked_id, blocker_id)",
        "CREATE INDEX IF NOT EXISTS idx_users_created ON users (created_at DESC, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_diamond_tx_user ON diamond_transactions (user_id, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_gifts_receiver ON gifts (receiver_id, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_gifts_sender ON gifts (sender_id, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_bookmarks_user ON bookmarks (user_id, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications (user_id, is_read, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_views_video ON video_views (video_id)",
        "CREATE INDEX IF NOT EXISTS idx_reports_created ON reports (created_at DESC)",
    ]
    for statement in indexes:
        db.execute(statement)

    users_without_uid = db.execute(
        "SELECT id FROM users WHERE uid IS NULL OR uid=''"
    ).fetchall()
    for user in users_without_uid:
        db.execute("UPDATE users SET uid=? WHERE id=?", (create_uid(db), user["id"]))

    db.execute("""UPDATE videos SET uploader_id=(
        SELECT users.id FROM users WHERE users.username=videos.creator
    ) WHERE uploader_id IS NULL""")
    db.execute("UPDATE videos SET privacy='public' WHERE privacy IS NULL OR privacy='' ")

    db.commit()
    db.close()


def migrate_legacy_sqlite_if_needed():
    """When DATA_DIR is changed, copy the old SQLite DB once instead of starting empty."""
    if USE_POSTGRES or os.path.exists(DB_FILE):
        return
    legacy = os.path.join(BASE_DIR, "ticktock.db")
    if os.path.abspath(legacy) != os.path.abspath(DB_FILE) and os.path.exists(legacy):
        try:
            os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
            shutil.copy2(legacy, DB_FILE)
            print("Tick Tock: preserved existing SQLite database at", DB_FILE)
        except Exception as error:
            print("Tick Tock database preservation warning:", error)

def init_db():
    if USE_POSTGRES:
        _init_postgres()
    else:
        _init_sqlite()


migrate_legacy_sqlite_if_needed()
init_db()


# =========================================================
# HELPERS
# =========================================================

def logged_in():

    return (
        "user_id"
        in session
    )


def valid_password(password):
    # New passwords: 8+ chars with upper/lowercase and a number.
    # Special characters are NOT required. Existing password hashes are untouched.
    if not password or len(password) < 8:
        return False
    if not re.search(r"[A-Z]", password):
        return False
    if not re.search(r"[a-z]", password):
        return False
    if not re.search(r"[0-9]", password):
        return False
    return True


# =========================================================
# HOME
# =========================================================

@app.route("/")
def index():

    return redirect(
        url_for("login")
    )


@app.route("/home")
def home():

    if not logged_in():

        return redirect(
            url_for("login")
        )

    db = get_db()

    user = db.execute(
        """
        SELECT *
        FROM users
        WHERE id=?
        """,
        (
            session["user_id"],
        )
    ).fetchone()

    db.close()

    if not user:

        session.clear()

        return redirect(
            url_for("login")
        )

    if not user["profile_complete"]:

        return redirect(
            url_for(
                "profile_setup"
            )
        )

    return render_template(
        "home.html",
        videos=[],
        logged_in=True,
        username=user["username"],
        uid=user["uid"],
        display_name=(user["display_name"] if "display_name" in user.keys() and user["display_name"] else user["username"].split("@")[0])
    )


# =========================================================
# REGISTER
# =========================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "GET":

        return render_template(
            "register.html"
        )

    email = request.form.get(
        "username",
        ""
    ).strip().lower()

    password = request.form.get(
        "password",
        ""
    )

    if not email.endswith(
        "@gmail.com"
    ):

        return render_template(
            "register.html",
            error=(
                "Please use a Gmail address."
            ),
            entered_email=email
        )

    if not valid_password(
        password
    ):

        return render_template(
            "register.html",
            error=(
                "Please enter a password."
            ),
            entered_email=email
        )

    db = get_db()

    existing = db.execute(
        """
        SELECT id
        FROM users
        WHERE lower(username)=?
        """,
        (email.lower(),)
    ).fetchone()

    if existing:

        db.close()

        return render_template(
            "register.html",
            error=(
                "Gmail already registered. "
                "Please login."
            ),
            entered_email=email
        )

    uid = create_uid(db)
    friend_uid = create_friend_uid(db)

    password_hash = (
        generate_password_hash(
            password
        )
    )

    db.execute(
        """
        INSERT INTO users
        (
            username,
            password,
            uid,
            friend_uid,
            profile_complete
        )
        VALUES (?, ?, ?, ?, 0)
        """,
        (
            email,
            password_hash,
            uid,
            friend_uid
        )
    )

    db.commit()

    db.close()

    return redirect(
        url_for("login")
    )


# =========================================================
# GOOGLE SIGN-IN
# =========================================================

def google_is_configured():
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def google_redirect_uri():
    # Set GOOGLE_REDIRECT_URI in Render for an explicit production callback.
    # Otherwise derive it from the current public request URL.
    return GOOGLE_REDIRECT_URI or url_for("google_callback", _external=True)


@app.route("/auth/google")
def google_login():
    if not google_is_configured():
        return render_template(
            "login.html",
            error="Google Login is not configured yet. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in Render Environment Variables."
        )

    state = secrets.token_urlsafe(32)
    session["google_oauth_state"] = state

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": google_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    from urllib.parse import urlencode
    return redirect(GOOGLE_AUTH_URL + "?" + urlencode(params))


@app.route("/auth/google/callback")
def google_callback():
    error = request.args.get("error", "").strip()
    if error:
        session.pop("google_oauth_state", None)
        return render_template("login.html", error="Google Login was cancelled or denied.")

    state = request.args.get("state", "")
    expected_state = session.pop("google_oauth_state", "")
    if not state or not expected_state or not hmac.compare_digest(state, expected_state):
        return render_template("login.html", error="Google Login security check failed. Please try again.")

    code = request.args.get("code", "").strip()
    if not code:
        return render_template("login.html", error="Google Login did not return an authorization code. Please try again.")

    if not google_is_configured():
        return render_template("login.html", error="Google Login is not configured on the server yet.")

    try:
        token_response = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": google_redirect_uri(),
                "grant_type": "authorization_code",
            },
            timeout=20,
        )
        if not token_response.ok:
            print("Google token error:", token_response.status_code, token_response.text[:1000])
            return render_template("login.html", error="Google Login could not be completed. Please try again.")

        token_data = token_response.json()
        access_token = token_data.get("access_token", "")
        if not access_token:
            return render_template("login.html", error="Google Login returned no access token. Please try again.")

        userinfo_response = requests.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        if not userinfo_response.ok:
            print("Google userinfo error:", userinfo_response.status_code, userinfo_response.text[:1000])
            return render_template("login.html", error="Could not read your Google account. Please try again.")

        info = userinfo_response.json()
        google_id = str(info.get("sub", "")).strip()
        email = str(info.get("email", "")).strip().lower()
        email_verified = info.get("email_verified") is True
        google_name = str(info.get("name", "")).strip()

        if not google_id or not email or not email_verified:
            return render_template("login.html", error="Google did not provide a verified email address.")

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE google_id=? OR lower(username)=? LIMIT 1",
            (google_id, email),
        ).fetchone()

        if user:
            db.execute(
                "UPDATE users SET google_id=?, email_verified=1 WHERE id=?",
                (google_id, user["id"]),
            )
            db.commit()
            user = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
            db.close()
        else:
            uid = create_uid(db)
            friend_uid = create_friend_uid(db)
            # Google users can still use password login later after setting a password
            # through the normal reset-password flow. The random hash is never exposed.
            random_password_hash = generate_password_hash(secrets.token_urlsafe(32))
            db.execute(
                """INSERT INTO users
                   (username, password, uid, friend_uid, display_name, profile_complete, email_verified, google_id)
                   VALUES (?, ?, ?, ?, ?, 0, 1, ?)""",
                (email, random_password_hash, uid, friend_uid, google_name or email.split("@")[0], google_id),
            )
            db.commit()
            user = db.execute("SELECT * FROM users WHERE id=?", (db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"],)).fetchone()
            db.close()

        _start_user_session(user)
        token = _issue_trusted_device(user["id"])
        response = redirect(url_for("home" if user["profile_complete"] else "profile_setup"))
        return _set_trusted_cookie(response, token)

    except Exception as error:
        print("Google Login exception:", error)
        return render_template("login.html", error="Google Login failed. Please try again.")


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE lower(username)=?", (email,)).fetchone()
    db.close()

    if not user:
        return render_template("login.html", error="Account not found ❌ Please register first.", register_required=True, entered_email=email)

    if not check_password_hash(user["password"], password):
        return render_template("login.html", error="Wrong password ❌", entered_email=email)

    # A trusted device skips OTP for normal logins. Switch Account deliberately forces OTP.
    force_otp = request.cookies.get(FORCE_OTP_COOKIE) == "1"
    trusted = None if force_otp else _trusted_user(email)
    if trusted:
        _start_user_session(trusted)
        return redirect(url_for("home" if trusted["profile_complete"] else "profile_setup"))

    otp = generate_otp()
    session["otp_hash"] = hash_otp(otp)
    session["otp_expires"] = time.time() + OTP_EXPIRY_SECONDS
    session["otp_attempts"] = 0
    session["otp_locked_until"] = 0
    session["otp_user_id"] = user["id"]
    session["otp_email"] = email

    sent = send_otp_email(email, otp)
    if not sent:
        clear_otp_session()
        return render_template("login.html", error="OTP could not be sent. Please check Render email configuration.", entered_email=email)

    return render_template("login.html", otp_required=True, entered_email=email, otp_message="Verification code sent to your email 📩")


# =========================================================
# VERIFY OTP
# =========================================================

@app.route(
    "/verify-otp",
    methods=["POST"]
)
def verify_otp():

    if "otp_user_id" not in session:

        return redirect(
            url_for("login")
        )

    now = time.time()

    locked_until = session.get(
        "otp_locked_until",
        0
    )

    if now < locked_until:

        remaining = int(
            locked_until - now
        )

        minutes = remaining // 60

        seconds = remaining % 60

        return render_template(
            "login.html",
            otp_required=True,
            entered_email=session.get(
                "otp_email",
                ""
            ),
            error=(
                "Too many wrong attempts ❌ "
                f"Try again in "
                f"{minutes}m {seconds}s."
            )
        )

    expires = session.get(
        "otp_expires",
        0
    )

    if now > expires:

        clear_otp_session()

        return render_template(
            "login.html",
            error=(
                "OTP expired ❌ "
                "Please login again."
            )
        )

    entered_otp = request.form.get(
        "otp",
        ""
    ).strip()

    if (
        not entered_otp.isdigit()
        or
        len(entered_otp) != 6
    ):

        return render_template(
            "login.html",
            otp_required=True,
            entered_email=session.get(
                "otp_email",
                ""
            ),
            error=(
                "Enter the 6-digit OTP ❌"
            )
        )

    if hash_otp(
        entered_otp
    ) != session.get(
        "otp_hash"
    ):

        attempts = (
            session.get(
                "otp_attempts",
                0
            )
            + 1
        )

        session["otp_attempts"] = (
            attempts
        )

        if attempts >= OTP_MAX_ATTEMPTS:

            session[
                "otp_locked_until"
            ] = (
                time.time()
                +
                OTP_LOCK_SECONDS
            )

            return render_template(
                "login.html",
                otp_required=True,
                entered_email=session.get(
                    "otp_email",
                    ""
                ),
                error=(
                    "3 wrong attempts ❌ "
                    "Login locked for "
                    "5 minutes."
                )
            )

        remaining = (
            OTP_MAX_ATTEMPTS
            -
            attempts
        )

        return render_template(
            "login.html",
            otp_required=True,
            entered_email=session.get(
                "otp_email",
                ""
            ),
            error=(
                f"Wrong OTP ❌ "
                f"{remaining} attempt(s) "
                "remaining."
            )
        )

    user_id = session[
        "otp_user_id"
    ]

    db = get_db()

    user = db.execute(
        """
        SELECT *
        FROM users
        WHERE id=?
        """,
        (user_id,)
    ).fetchone()

    db.close()

    if not user:

        clear_otp_session()

        return redirect(
            url_for("login")
        )

    # OTP proves ownership of the email. Remember this device for 30 days.
    token = _issue_trusted_device(user["id"])
    db = get_db()
    db.execute("UPDATE users SET email_verified=1 WHERE id=?", (user["id"],))
    db.commit()
    db.close()
    clear_otp_session()
    _start_user_session(user)

    response = redirect(url_for("home" if user["profile_complete"] else "profile_setup"))
    return _set_trusted_cookie(response, token)


# =========================================================
# RESEND OTP
# =========================================================

@app.route(
    "/resend-otp",
    methods=["POST"]
)
def resend_otp():

    if "otp_user_id" not in session:

        return redirect(
            url_for("login")
        )

    now = time.time()

    locked_until = session.get(
        "otp_locked_until",
        0
    )

    if now < locked_until:

        remaining = int(
            locked_until - now
        )

        return render_template(
            "login.html",
            otp_required=True,
            entered_email=session.get(
                "otp_email",
                ""
            ),
            error=(
                f"Please wait "
                f"{remaining} seconds "
                "before trying again."
            )
        )

    db = get_db()

    user = db.execute(
        """
        SELECT *
        FROM users
        WHERE id=?
        """,
        (
            session["otp_user_id"],
        )
    ).fetchone()

    db.close()

    if not user:

        clear_otp_session()

        return redirect(
            url_for("login")
        )

    otp = generate_otp()

    session["otp_hash"] = (
        hash_otp(otp)
    )

    session["otp_expires"] = (
        time.time()
        +
        OTP_EXPIRY_SECONDS
    )

    session["otp_attempts"] = 0

    session["otp_locked_until"] = 0

    session["otp_email"] = (
        user["username"]
    )

    sent = send_otp_email(
        user["username"],
        otp
    )

    if not sent:

        return render_template(
            "login.html",
            otp_required=True,
            entered_email=user[
                "username"
            ],
            error=(
                "Could not send "
                "new OTP ❌"
            )
        )

    return render_template(
        "login.html",
        otp_required=True,
        entered_email=user[
            "username"
        ],
        otp_message=(
            "New OTP sent 📩 "
            "It expires in 3 minutes."
        )
    )


# =========================================================
# PROFILE SETUP
# =========================================================

@app.route("/profile-setup", methods=["GET", "POST"])
@app.route("/profile", methods=["GET", "POST"])
def profile_setup():
    """Modern profile onboarding/edit page. Existing account data is preserved."""
    if not logged_in():
        return redirect(url_for("login"))

    db = get_db()
    current = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    if not current:
        db.close()
        session.clear()
        return redirect(url_for("login"))

    if request.method == "GET":
        data = dict(current)
        db.close()
        return render_template("profile.html", user=data, uid=current["uid"])

    gender = request.form.get("gender", "").strip().lower()
    if gender not in {"male", "female", "other", "prefer_not_to_say", ""}:
        gender = ""

    birth_date = request.form.get("birth_date", "").strip()
    display_name = request.form.get("display_name", "").strip()[:60]
    bio = request.form.get("bio", "").strip()[:160]
    location = request.form.get("location", "").strip()[:80]

    # Keep old profile values when an optional field is left blank.
    if not display_name:
        display_name = (current["display_name"] if "display_name" in current.keys() and current["display_name"] else current["username"].split("@")[0])

    age = current["age"]
    if birth_date:
        try:
            dob = datetime.date.fromisoformat(birth_date)
            today = datetime.date.today()
            if dob < datetime.date(1980, 1, 1) or dob > datetime.date(2021, 12, 31) or dob > today:
                raise ValueError
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        except ValueError:
            db.close()
            return render_template("profile.html", user=dict(current), uid=current["uid"], error="Choose a valid birthday between 1980 and 2021.")
    elif age is None:
        db.close()
        return render_template("profile.html", user=dict(current), uid=current["uid"], error="Please choose your birthday.")

    photo = request.files.get("photo")
    photo_filename = None
    if photo and photo.filename:
        extension = os.path.splitext(photo.filename)[1].lower()
        allowed = {".jpg", ".jpeg", ".png", ".webp"}
        if extension not in allowed:
            db.close()
            return render_template("profile.html", user=dict(current), uid=current["uid"], error="Use JPG, PNG or WEBP for your profile photo.")
        photo_filename = f"profile_{session['user_id']}{extension}"
        photo.save(os.path.join(UPLOAD_FOLDER, secure_filename(photo_filename)))

    if photo_filename:
        db.execute("""UPDATE users SET display_name=?, gender=?, birth_date=?, age=?, photo=?, bio=?, location=?, profile_complete=1 WHERE id=?""",
                   (display_name, gender, birth_date or None, age, photo_filename, bio, location, session["user_id"]))
    else:
        db.execute("""UPDATE users SET display_name=?, gender=?, birth_date=?, age=?, bio=?, location=?, profile_complete=1 WHERE id=?""",
                   (display_name, gender, birth_date or None, age, bio, location, session["user_id"]))
    db.commit()
    db.close()
    return redirect(url_for("home"))

# =========================================================
# MY PROFILE API
# =========================================================

@app.route("/api/me")
def api_me():

    if not logged_in():

        return jsonify({
            "success": False
        }), 401

    db = get_db()

    user = db.execute(
        """
        SELECT
            id,
            username,
            uid,
            friend_uid,
            gender,
            age,
            birth_date,
            display_name,
            photo,
            bio,
            location
        FROM users
        WHERE id=?
        """,
        (
            session["user_id"],
        )
    ).fetchone()

    db.close()

    if not user:

        return jsonify({
            "success": False
        }), 404

    return jsonify({
        "success": True,
        "user": dict(user)
    })


# =========================================================
# USER BY UID
# =========================================================

@app.route("/api/user/<uid>")
def find_user(uid):

    if not logged_in():

        return jsonify({
            "success": False,
            "login_required": True
        }), 401

    db = get_db()

    user = db.execute(
        """
        SELECT
            id,
            username,
            uid,
            friend_uid,
            gender,
            age,
            birth_date,
            display_name,
            photo,
            bio,
            location
        FROM users
        WHERE uid=? OR friend_uid=?
        """,
        (
            uid,
            uid,
        )
    ).fetchone()

    db.close()

    if not user:

        return jsonify({
            "success": False,
            "message": "User not found."
        }), 404

    return jsonify({
        "success": True,
        "user": dict(user)
    })


# =========================================================
# SEND FRIEND REQUEST
# =========================================================

@app.route(
    "/api/friend-request/<uid>",
    methods=["POST"]
)
def send_friend_request(uid):

    if not logged_in():

        return jsonify({
            "success": False,
            "login_required": True
        }), 401

    db = get_db()

    target = db.execute(
        """
        SELECT id
        FROM users
        WHERE uid=? OR friend_uid=?
        """,
        (
            uid,
            uid,
        )
    ).fetchone()

    if not target:

        db.close()

        return jsonify({
            "success": False,
            "message": "User not found."
        }), 404

    sender = session["user_id"]

    receiver = target["id"]

    if sender == receiver:

        db.close()

        return jsonify({
            "success": False,
            "message": (
                "You cannot add yourself."
            )
        })

    blocked = db.execute(
        """
        SELECT id
        FROM blocks
        WHERE
            (
                blocker_id=?
                AND
                blocked_id=?
            )
            OR
            (
                blocker_id=?
                AND
                blocked_id=?
            )
        """,
        (
            sender,
            receiver,
            receiver,
            sender
        )
    ).fetchone()

    if blocked:

        db.close()

        return jsonify({
            "success": False,
            "message": (
                "Friend request unavailable."
            )
        })

    friendship = db.execute(
        """
        SELECT id
        FROM friends
        WHERE
            (
                user1_id=?
                AND
                user2_id=?
            )
            OR
            (
                user1_id=?
                AND
                user2_id=?
            )
        """,
        (
            sender,
            receiver,
            receiver,
            sender
        )
    ).fetchone()

    if friendship:

        db.close()

        return jsonify({
            "success": False,
            "message": (
                "You are already friends."
            )
        })

    existing = db.execute(
        """
        SELECT
            id,
            status,
            sender_id
        FROM friend_requests
        WHERE
            (
                sender_id=?
                AND
                receiver_id=?
            )
            OR
            (
                sender_id=?
                AND
                receiver_id=?
            )
        """,
        (
            sender,
            receiver,
            receiver,
            sender
        )
    ).fetchone()

    if existing:

        db.close()

        if existing["status"] == "pending":

            return jsonify({
                "success": False,
                "message": (
                    "Friend request "
                    "already pending."
                )
            })

        if existing["status"] == "accepted":

            return jsonify({
                "success": False,
                "message": (
                    "Already friends."
                )
            })

    db.execute(
        """
        INSERT INTO friend_requests
        (
            sender_id,
            receiver_id,
            status
        )
        VALUES (?, ?, 'pending')
        """,
        (
            sender,
            receiver
        )
    )

    db.commit()

    db.close()

    return jsonify({
        "success": True,
        "message": (
            "Friend request sent! 👥"
        )
    })


# =========================================================
# FRIEND REQUESTS
# =========================================================

@app.route("/api/friend-requests")
def get_friend_requests():

    if not logged_in():

        return jsonify({
            "success": False
        }), 401

    db = get_db()

    rows = db.execute(
        """
        SELECT
            friend_requests.id,
            friend_requests.status,
            friend_requests.created_at,
            users.username,
            users.uid,
            users.friend_uid,
            users.photo
        FROM friend_requests
        JOIN users
            ON users.id =
            friend_requests.sender_id
        WHERE
            friend_requests.receiver_id=?
            AND
            friend_requests.status='pending'
        ORDER BY friend_requests.id DESC
        """,
        (
            session["user_id"],
        )
    ).fetchall()

    db.close()

    return jsonify([
        dict(row)
        for row in rows
    ])


# =========================================================
# ACCEPT FRIEND
# =========================================================

@app.route(
    "/api/friend-request/<int:request_id>/accept",
    methods=["POST"]
)
def accept_request(request_id):

    if not logged_in():

        return jsonify({
            "success": False
        }), 401

    db = get_db()

    req = db.execute(
        """
        SELECT *
        FROM friend_requests
        WHERE
            id=?
            AND
            receiver_id=?
            AND
            status='pending'
        """,
        (
            request_id,
            session["user_id"]
        )
    ).fetchone()

    if not req:

        db.close()

        return jsonify({
            "success": False,
            "message": (
                "Request not found."
            )
        }), 404

    db.execute(
        """
        UPDATE friend_requests
        SET status='accepted'
        WHERE id=?
        """,
        (
            request_id,
        )
    )

    db.execute(
        """
        INSERT INTO friends
        (
            user1_id,
            user2_id
        )
        VALUES (?, ?)
            ON CONFLICT DO NOTHING
        """,
        (
            req["sender_id"],
            req["receiver_id"]
        )
    )

    db.commit()

    db.close()

    return jsonify({
        "success": True,
        "message": (
            "Friend request accepted! 🎉"
        )
    })


# =========================================================
# REJECT FRIEND
# =========================================================

@app.route(
    "/api/friend-request/<int:request_id>/reject",
    methods=["POST"]
)
def reject_request(request_id):

    if not logged_in():

        return jsonify({
            "success": False
        }), 401

    db = get_db()

    db.execute(
        """
        UPDATE friend_requests
        SET status='rejected'
        WHERE
            id=?
            AND
            receiver_id=?
        """,
        (
            request_id,
            session["user_id"]
        )
    )

    db.commit()

    db.close()

    return jsonify({
        "success": True,
        "message": (
            "Request rejected."
        )
    })


# =========================================================
# FRIEND LIST
# =========================================================

@app.route("/api/friends")
def get_friends():

    if not logged_in():

        return jsonify({
            "success": False
        }), 401

    user_id = session["user_id"]

    db = get_db()

    rows = db.execute(
        """
        SELECT
            users.id,
            users.username,
            users.uid,
            users.friend_uid,
            users.photo,
            users.bio,
            users.location
        FROM friends
        JOIN users
            ON users.id =
            CASE
                WHEN friends.user1_id=?
                THEN friends.user2_id
                ELSE friends.user1_id
            END
        WHERE
            friends.user1_id=?
            OR
            friends.user2_id=?
        ORDER BY users.username
        """,
        (
            user_id,
            user_id,
            user_id
        )
    ).fetchall()

    db.close()

    return jsonify([
        dict(row)
        for row in rows
    ])


# =========================================================
# REMOVE FRIEND
# =========================================================

@app.route(
    "/api/friend/remove/<uid>",
    methods=["POST"]
)
def remove_friend(uid):

    if not logged_in():

        return jsonify({
            "success": False
        }), 401

    db = get_db()

    target = db.execute(
        """
        SELECT id
        FROM users
        WHERE uid=? OR friend_uid=?
        """,
        (
            uid,
            uid,
        )
    ).fetchone()

    if not target:

        db.close()

        return jsonify({
            "success": False,
            "message": "User not found."
        }), 404

    user_id = session["user_id"]

    other_id = target["id"]

    db.execute(
        """
        DELETE FROM friends
        WHERE
            (
                user1_id=?
                AND
                user2_id=?
            )
            OR
            (
                user1_id=?
                AND
                user2_id=?
            )
        """,
        (
            user_id,
            other_id,
            other_id,
            user_id
        )
    )

    db.commit()

    db.close()

    return jsonify({
        "success": True,
        "message": "Friend removed."
    })


# =========================================================
# BLOCK
# =========================================================

@app.route(
    "/api/block/<uid>",
    methods=["POST"]
)
def block_user(uid):

    if not logged_in():

        return jsonify({
            "success": False
        }), 401

    db = get_db()

    target = db.execute(
        """
        SELECT id
        FROM users
        WHERE uid=? OR friend_uid=?
        """,
        (
            uid,
            uid,
        )
    ).fetchone()

    if not target:

        db.close()

        return jsonify({
            "success": False,
            "message": "User not found."
        }), 404

    user_id = session["user_id"]

    other_id = target["id"]

    if user_id == other_id:

        db.close()

        return jsonify({
            "success": False,
            "message": (
                "You cannot block yourself."
            )
        })

    db.execute(
        """
        INSERT INTO blocks
        (
            blocker_id,
            blocked_id
        )
        VALUES (?, ?)
            ON CONFLICT DO NOTHING
        """,
        (
            user_id,
            other_id
        )
    )

    db.execute(
        """
        DELETE FROM friends
        WHERE
            (
                user1_id=?
                AND
                user2_id=?
            )
            OR
            (
                user1_id=?
                AND
                user2_id=?
            )
        """,
        (
            user_id,
            other_id,
            other_id,
            user_id
        )
    )

    db.execute(
        """
        DELETE FROM friend_requests
        WHERE
            (
                sender_id=?
                AND
                receiver_id=?
            )
            OR
            (
                sender_id=?
                AND
                receiver_id=?
            )
        """,
        (
            user_id,
            other_id,
            other_id,
            user_id
        )
    )

    db.commit()

    db.close()

    return jsonify({
        "success": True,
        "message": "User blocked."
    })


# =========================================================
# UNBLOCK
# =========================================================

@app.route(
    "/api/unblock/<uid>",
    methods=["POST"]
)
def unblock_user(uid):

    if not logged_in():

        return jsonify({
            "success": False
        }), 401

    db = get_db()

    target = db.execute(
        """
        SELECT id
        FROM users
        WHERE uid=? OR friend_uid=?
        """,
        (
            uid,
            uid,
        )
    ).fetchone()

    if target:

        db.execute(
            """
            DELETE FROM blocks
            WHERE
                blocker_id=?
                AND
                blocked_id=?
            """,
            (
                session["user_id"],
                target["id"]
            )
        )

        db.commit()

    db.close()

    return jsonify({
        "success": True,
        "message": "User unblocked."
    })


# =========================================================
# BLOCKED USERS
# =========================================================

@app.route("/api/blocked")
def blocked_users():

    if not logged_in():

        return jsonify({
            "success": False
        }), 401

    db = get_db()

    rows = db.execute(
        """
        SELECT
            users.username,
            users.uid,
            users.friend_uid,
            users.photo
        FROM blocks
        JOIN users
            ON users.id=blocks.blocked_id
        WHERE
            blocks.blocker_id=?
        ORDER BY users.username
        """,
        (
            session["user_id"],
        )
    ).fetchall()

    db.close()

    return jsonify([
        dict(row)
        for row in rows
    ])



# =========================================================
# PUBLIC USERS + FOLLOWING
# =========================================================

@app.route("/api/users")
def discover_users():
    if not logged_in():
        return jsonify({
            "success": False,
            "login_required": True
        }), 401

    me = session["user_id"]
    db = get_db()

    rows = db.execute(
        """
        SELECT
            users.id,
            users.username,
            users.uid,
            users.gender,
            users.photo,
            users.bio,
            users.created_at,
            EXISTS(
                SELECT 1
                FROM follows f
                WHERE f.follower_id=?
                  AND f.following_id=users.id
            ) AS is_following,
            (
                SELECT COUNT(*)
                FROM follows f2
                WHERE f2.following_id=users.id
            ) AS followers_count,
            (
                SELECT COUNT(*)
                FROM follows f3
                WHERE f3.follower_id=users.id
            ) AS following_count
        FROM users
        WHERE users.id != ?
          AND users.profile_complete=1
        ORDER BY users.id DESC
        LIMIT 30
        """,
        (me, me)
    ).fetchall()

    db.close()

    return jsonify([dict(row) for row in rows])


# =========================================================
# V3 SOCIAL HELPERS
# =========================================================

def add_notification(db, user_id, actor_id, ntype, message, video_id=None):
    if user_id and actor_id and int(user_id) == int(actor_id):
        return
    db.execute("INSERT INTO notifications (user_id, actor_id, type, video_id, message) VALUES (?, ?, ?, ?, ?)",
               (user_id, actor_id, ntype, video_id, message))


@app.route("/api/follow/<uid>", methods=["POST"])
def follow_user(uid):
    if not logged_in():
        return jsonify({
            "success": False,
            "login_required": True
        }), 401

    db = get_db()

    target = db.execute(
        "SELECT id FROM users WHERE uid=? OR friend_uid=?",
        (uid, uid)
    ).fetchone()

    if not target:
        db.close()
        return jsonify({
            "success": False,
            "message": "User not found."
        }), 404

    me = session["user_id"]
    target_id = target["id"]

    if me == target_id:
        db.close()
        return jsonify({
            "success": False,
            "message": "You cannot follow yourself."
        }), 400

    blocked = db.execute(
        """
        SELECT id FROM blocks
        WHERE (blocker_id=? AND blocked_id=?)
           OR (blocker_id=? AND blocked_id=?)
        """,
        (me, target_id, target_id, me)
    ).fetchone()

    if blocked:
        db.close()
        return jsonify({
            "success": False,
            "message": "Follow unavailable."
        }), 403

    existing = db.execute(
        """
        SELECT id
        FROM follows
        WHERE follower_id=? AND following_id=?
        """,
        (me, target_id)
    ).fetchone()

    if existing:
        db.execute(
            "DELETE FROM follows WHERE id=?",
            (existing["id"],)
        )
        following = False
    else:
        db.execute(
            """
            INSERT INTO follows
            (follower_id, following_id)
            VALUES (?, ?)
            ON CONFLICT DO NOTHING
            """,
            (me, target_id)
        )
        following = True
        target_user = db.execute("SELECT username FROM users WHERE id=?", (target_id,)).fetchone()
        add_notification(db, target_id, me, "follow", f"@{session.get('username','user')} started following you")

    count = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM follows
        WHERE following_id=?
        """,
        (target_id,)
    ).fetchone()["total"]

    db.commit()
    db.close()

    return jsonify({
        "success": True,
        "following": following,
        "followers_count": count
    })


@app.route("/api/followers")
def api_followers():
    if not logged_in():
        return jsonify({"success": False}), 401

    db = get_db()
    rows = db.execute(
        """
        SELECT users.id, users.username, users.uid, users.friend_uid,
               users.gender, users.photo, users.bio
        FROM follows
        JOIN users ON users.id=follows.follower_id
        WHERE follows.following_id=?
        ORDER BY follows.id DESC
        """,
        (session["user_id"],)
    ).fetchall()
    db.close()
    return jsonify([dict(row) for row in rows])


@app.route("/api/following")
def api_following():
    if not logged_in():
        return jsonify({"success": False}), 401

    db = get_db()
    rows = db.execute(
        """
        SELECT users.id, users.username, users.uid, users.friend_uid,
               users.gender, users.photo, users.bio
        FROM follows
        JOIN users ON users.id=follows.following_id
        WHERE follows.follower_id=?
        ORDER BY follows.id DESC
        """,
        (session["user_id"],)
    ).fetchall()
    db.close()
    return jsonify([dict(row) for row in rows])


# =========================================================
# V3 FEATURES: SEARCH / SAVED / NOTIFICATIONS / VIEWS / REPORTS
# =========================================================

@app.route("/api/search")
def api_search():
    q = str(request.args.get("q", "")).strip()[:80]
    if not q:
        return jsonify({"users": [], "videos": []})
    db = get_db(); like = f"%{q}%"
    users = db.execute("SELECT id, username, uid, friend_uid, gender, photo, bio FROM users WHERE lower(username) LIKE lower(?) OR lower(uid) LIKE lower(?) OR lower(friend_uid) LIKE lower(?) ORDER BY id DESC LIMIT 20", (like, like, like)).fetchall()
    videos = db.execute("SELECT id, title, url, creator, source, caption, tags, uploader_id FROM videos WHERE privacy='public' AND (lower(title) LIKE lower(?) OR lower(COALESCE(caption,'')) LIKE lower(?) OR lower(COALESCE(tags,'')) LIKE lower(?)) ORDER BY created_at DESC LIMIT 20", (like,like,like)).fetchall()
    db.close()
    return jsonify({"users":[dict(x) for x in users],"videos":[dict(x) for x in videos]})

@app.route("/api/bookmark/<video_id>", methods=["POST"])
def bookmark_video(video_id):
    if not logged_in(): return jsonify({"success":False,"login_required":True}),401
    db=get_db(); row=db.execute("SELECT id FROM bookmarks WHERE user_id=? AND video_id=?",(session["user_id"],video_id)).fetchone()
    if row:
        db.execute("DELETE FROM bookmarks WHERE id=?",(row["id"],)); saved=False
    else:
        db.execute("INSERT INTO bookmarks (user_id,video_id) VALUES (?,?)",(session["user_id"],video_id)); saved=True
    db.commit(); db.close(); return jsonify({"success":True,"saved":saved})

@app.route("/api/bookmarks")
def api_bookmarks():
    if not logged_in(): return jsonify({"success":False}),401
    db=get_db(); rows=db.execute("SELECT b.video_id,b.created_at,v.title,v.url,v.creator,v.caption,v.tags FROM bookmarks b LEFT JOIN videos v ON CAST(v.id AS TEXT)=b.video_id WHERE b.user_id=? ORDER BY b.id DESC LIMIT 100",(session["user_id"],)).fetchall(); db.close()
    return jsonify([dict(x) for x in rows])

@app.route("/api/notifications")
def api_notifications():
    if not logged_in(): return jsonify({"success":False}),401
    db=get_db(); rows=db.execute("SELECT id,type,message,video_id,is_read,created_at FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 50",(session["user_id"],)).fetchall(); unread=db.execute("SELECT COUNT(*) AS n FROM notifications WHERE user_id=? AND is_read=0",(session["user_id"],)).fetchone()["n"]; db.close()
    return jsonify({"notifications":[dict(x) for x in rows],"unread":int(unread)})

@app.route("/api/notifications/read", methods=["POST"])
def read_notifications():
    if not logged_in(): return jsonify({"success":False}),401
    db=get_db(); db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?",(session["user_id"],)); db.commit(); db.close(); return jsonify({"success":True})

@app.route("/api/view/<video_id>", methods=["POST"])
def video_view(video_id):
    db=get_db(); uid=session.get("user_id")
    db.execute("INSERT INTO video_views (user_id,video_id) VALUES (?,?)",(uid,video_id)); db.commit(); n=db.execute("SELECT COUNT(*) AS n FROM video_views WHERE video_id=?",(video_id,)).fetchone()["n"]; db.close(); return jsonify({"success":True,"views":int(n)})

@app.route("/api/report", methods=["POST"])
def report_content():
    if not logged_in(): return jsonify({"success":False,"login_required":True}),401
    data=request.get_json(silent=True) or {}; video_id=str(data.get("video_id","")).strip() or None; uid=str(data.get("uid","")).strip() or None; reason=str(data.get("reason","Other")).strip()[:100]
    if reason not in {"Spam","Harassment","Nudity","Violence","Copyright","Other"}: reason="Other"
    db=get_db(); target=db.execute("SELECT id FROM users WHERE uid=?",(uid,)).fetchone() if uid else None
    db.execute("INSERT INTO reports (reporter_id,video_id,reported_user_id,reason) VALUES (?,?,?,?)",(session["user_id"],video_id,target["id"] if target else None,reason)); db.commit(); db.close(); return jsonify({"success":True,"message":"Report received. Thank you."})

@app.route("/api/creator-stats")
def creator_stats():
    if not logged_in(): return jsonify({"success":False}),401
    db=get_db(); uid=session["user_id"]
    followers=db.execute("SELECT COUNT(*) AS n FROM follows WHERE following_id=?",(uid,)).fetchone()["n"]
    following=db.execute("SELECT COUNT(*) AS n FROM follows WHERE follower_id=?",(uid,)).fetchone()["n"]
    videos=db.execute("SELECT COUNT(*) AS n FROM videos WHERE uploader_id=?",(uid,)).fetchone()["n"]
    gifts=db.execute("SELECT COALESCE(SUM(diamonds),0) AS n FROM gifts WHERE receiver_id=?",(uid,)).fetchone()["n"]
    views=db.execute("SELECT COUNT(*) AS n FROM video_views vv JOIN videos v ON CAST(v.id AS TEXT)=vv.video_id WHERE v.uploader_id=?",(uid,)).fetchone()["n"]
    db.close(); return jsonify({"success":True,"followers":int(followers),"following":int(following),"videos":int(videos),"gift_diamonds":int(gifts or 0),"views":int(views)})

# =========================================================
# PIXABAY
# =========================================================

PIXABAY_API_KEY = os.environ.get(
    "PIXABAY_API_KEY"
)

PIXABAY_URL = (
    "https://pixabay.com/api/videos/"
)


SEARCHES = [

    "India",

    "Indian",

    "Hyderabad",

    "Telangana",

    "Indian food",

    "Indian festival",

    "Indian dance",

    "Indian culture",

    "India travel",

    "cricket",

    "Indian wedding"
]


VIDEO_CACHE = []
VIDEO_CACHE_TIME = 0.0
VIDEO_CACHE_TTL = 30 * 60

def get_pixabay_videos():

    global VIDEO_CACHE, VIDEO_CACHE_TIME

    # Small in-process cache: fast feed, low RAM, and fewer external API calls.
    if VIDEO_CACHE and (time.time() - VIDEO_CACHE_TIME) < VIDEO_CACHE_TTL:

        result = VIDEO_CACHE.copy()

        random.shuffle(result)

        return result

    if not PIXABAY_API_KEY:

        print(
            "PIXABAY_API_KEY missing."
        )

        return []

    result = []

    queries = random.sample(
        SEARCHES,
        min(
            4,
            len(SEARCHES)
        )
    )

    for query in queries:

        try:

            response = requests.get(
                PIXABAY_URL,
                params={
                    "key":
                        PIXABAY_API_KEY,

                    "q":
                        query,

                    "per_page":
                        12,

                    "video_type":
                        "all"
                },
                timeout=8
            )

            if response.status_code != 200:

                continue

            data = response.json()

            for item in data.get(
                "hits",
                []
            ):

                duration = item.get(
                    "duration",
                    9999
                )

                if duration > 30:

                    continue

                files = item.get(
                    "videos",
                    {}
                )

                selected = None

                for quality in [

                    "small",

                    "medium",

                    "tiny",

                    "large"

                ]:

                    info = files.get(
                        quality
                    )

                    if info:

                        selected = info

                        break

                if not selected:

                    continue

                video_url = selected.get(
                    "url"
                )

                if not video_url:

                    continue

                result.append({

                    "id":
                        "pixabay_"
                        +
                        str(
                            item.get(
                                "id"
                            )
                        ),

                    "title":
                        query.title()
                        +
                        " Reel",

                    "url":
                        video_url,

                    "creator":
                        item.get(
                            "user",
                            "Creator"
                        ),

                    "duration":
                        duration,

                    "source":
                        "pixabay"
                })

        except Exception as error:

            print(
                "Pixabay error:",
                error
            )

    unique = {}

    for video in result:

        unique[
            video["id"]
        ] = video

    VIDEO_CACHE = list(unique.values())[:24]
    VIDEO_CACHE_TIME = time.time()

    random.shuffle(VIDEO_CACHE)

    print(
        "Automatic Reels:",
        len(VIDEO_CACHE)
    )

    return VIDEO_CACHE


@app.route("/api/videos")
def api_videos():

    return jsonify(
        get_pixabay_videos()
    )


@app.route("/api/refresh")
def refresh_videos():

    global VIDEO_CACHE, VIDEO_CACHE_TIME

    VIDEO_CACHE = []
    VIDEO_CACHE_TIME = 0.0

    return jsonify({
        "success": True,
        "videos":
            get_pixabay_videos()
    })


# =========================================================
# LIKES
# =========================================================

@app.route(
    "/api/like/<video_id>",
    methods=["POST"]
)
def like_video(video_id):

    if not logged_in():

        return jsonify({
            "success": False,
            "login_required": True
        }), 401

    db = get_db()

    existing = db.execute(
        """
        SELECT id
        FROM likes
        WHERE
            user_id=?
            AND
            video_id=?
        """,
        (
            session["user_id"],
            video_id
        )
    ).fetchone()

    if existing:

        db.execute(
            """
            DELETE FROM likes
            WHERE id=?
            """,
            (
                existing["id"],
            )
        )

        liked = False

    else:

        db.execute(
            """
            INSERT INTO likes
            (
                user_id,
                video_id
            )
            VALUES (?, ?)
            """,
            (
                session["user_id"],
                video_id
            )
        )

        liked = True

    count = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM likes
        WHERE video_id=?
        """,
        (
            video_id,
        )
    ).fetchone()["total"]

    if liked:
        owner = db.execute("SELECT uploader_id, creator FROM videos WHERE CAST(id AS TEXT)=? OR url=?", (video_id, video_id)).fetchone()
        if owner and owner["uploader_id"]:
            add_notification(db, owner["uploader_id"], session["user_id"], "like", f"@{session.get('username','user')} liked your video", video_id)

    db.commit()

    db.close()

    return jsonify({
        "success": True,
        "liked": liked,
        "count": count
    })


# =========================================================
# COMMENTS
# =========================================================

@app.route(
    "/api/comment/<video_id>",
    methods=["POST"]
)
def add_comment(video_id):

    if not logged_in():

        return jsonify({
            "success": False,
            "login_required": True
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    comment = str(
        data.get(
            "comment",
            ""
        )
    ).strip()

    if not comment:

        return jsonify({
            "success": False,
            "message": "Empty comment."
        }), 400

    db = get_db()

    db.execute(
        """
        INSERT INTO comments
        (
            user_id,
            video_id,
            comment
        )
        VALUES (?, ?, ?)
        """,
        (
            session["user_id"],
            video_id,
            comment
        )
    )

    owner = db.execute("SELECT uploader_id FROM videos WHERE CAST(id AS TEXT)=? OR url=?", (video_id, video_id)).fetchone()
    if owner and owner["uploader_id"]:
        add_notification(db, owner["uploader_id"], session["user_id"], "comment", f"@{session.get('username','user')} commented on your video", video_id)

    db.commit()

    db.close()

    return jsonify({
        "success": True,
        "username":
            session["username"],
        "comment":
            comment
    })


@app.route(
    "/api/comments/<video_id>"
)
def get_comments(video_id):

    db = get_db()

    rows = db.execute(
        """
        SELECT
            comments.comment,
            comments.created_at,
            users.username
        FROM comments
        JOIN users
            ON users.id=comments.user_id
        WHERE
            comments.video_id=?
        ORDER BY comments.id DESC
        """,
        (
            video_id,
        )
    ).fetchall()

    db.close()

    return jsonify([
        dict(row)
        for row in rows
    ])


# =========================================================
# SHARES
# =========================================================

@app.route(
    "/api/share/<video_id>",
    methods=["POST"]
)
def share_video(video_id):

    if not logged_in():

        return jsonify({
            "success": False,
            "login_required": True
        }), 401

    db = get_db()

    db.execute(
        """
        INSERT INTO shares
        (
            user_id,
            video_id
        )
        VALUES (?, ?)
            ON CONFLICT DO NOTHING
        """,
        (
            session["user_id"],
            video_id
        )
    )

    count = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM shares
        WHERE video_id=?
        """,
        (
            video_id,
        )
    ).fetchone()["total"]

    db.commit()

    db.close()

    return jsonify({
        "success": True,
        "count": count
    })


# =========================================================
# FRIEND REELS
# =========================================================

@app.route("/api/friend-reels")
def friend_reels():
    if not logged_in():
        return jsonify({"success": False, "login_required": True}), 401
    me = session["user_id"]
    db = get_db()
    rows = db.execute("""
        SELECT videos.id, videos.title, videos.url, videos.creator, videos.caption, videos.tags, videos.created_at,
               users.uid AS creator_uid, users.friend_uid AS creator_friend_uid, users.username, users.gender, users.photo
        FROM videos
        JOIN friends ON (
            (friends.user1_id=? AND friends.user2_id=videos.uploader_id) OR
            (friends.user2_id=? AND friends.user1_id=videos.uploader_id)
        )
        JOIN users ON users.id=videos.uploader_id
        WHERE (videos.privacy='public' OR videos.privacy IS NULL)
        ORDER BY videos.created_at DESC, videos.id DESC
        LIMIT 30
    """, (me, me)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


# =========================================================
# UPLOAD
# =========================================================

ALLOWED_VIDEO = {

    "mp4",

    "webm",

    "mov",

    "m4v"
}


@app.route(
    "/upload",
    methods=["GET", "POST"]
)
def upload():

    if not logged_in():

        return redirect(
            url_for("login")
        )

    if request.method == "GET":

        return render_template(
            "upload.html"
        )

    file = request.files.get(
        "video"
    )

    if not file or not file.filename:

        return "Please select a video."

    extension = (
        file.filename
        .rsplit(".", 1)[-1]
        .lower()
    )

    if extension not in ALLOWED_VIDEO:

        return (
            "Only MP4, WEBM, MOV "
            "and M4V files are allowed."
        )

    filename = secure_filename(
        file.filename
    )

    name, ext = os.path.splitext(
        filename
    )

    filename = (
        name
        +
        "_"
        +
        str(
            random.randint(
                100000,
                999999
            )
        )
        +
        ext
    )

    file.save(
        os.path.join(
            UPLOAD_FOLDER,
            filename
        )
    )

    db = get_db()

    caption = request.form.get(
        "caption",
        ""
    ).strip()[:500]

    tags = request.form.get(
        "tags",
        ""
    ).strip()[:500]

    privacy = request.form.get(
        "privacy",
        "public"
    ).strip().lower()

    if privacy not in ("public", "private"):
        privacy = "public"

    db.execute(
        """
        INSERT INTO videos
        (
            title,
            url,
            creator,
            source,
            caption,
            tags,
            privacy,
            uploader_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            filename,
            url_for(
                "uploaded_video",
                filename=filename
            ),
            session["username"],
            "user_upload",
            caption,
            tags,
            privacy,
            session["user_id"]
        )
    )

    db.commit()

    db.close()

    return redirect(
        url_for("home")
    )


# =========================================================
# UPLOAD API
# =========================================================

@app.route("/api/uploads")
def api_uploads():

    db = get_db()

    current_user_id = session.get("user_id")

    rows = db.execute(
        """
        SELECT
            videos.id,
            videos.title,
            videos.url,
            videos.creator,
            videos.source,
            videos.caption,
            videos.tags,
            videos.created_at,
            users.uid AS creator_uid,
            users.gender AS creator_gender,
            users.photo AS creator_photo,
            (
                SELECT COUNT(*)
                FROM follows f
                WHERE f.following_id=users.id
            ) AS creator_followers,
            EXISTS(
                SELECT 1
                FROM follows mef
                WHERE mef.follower_id=?
                  AND mef.following_id=users.id
            ) AS is_following
        FROM videos
        LEFT JOIN users
            ON users.id=videos.uploader_id
        WHERE videos.privacy='public'
           OR videos.privacy IS NULL
        ORDER BY videos.created_at DESC NULLS LAST, videos.id DESC
        LIMIT 24
        """,
        (current_user_id or 0,)
    ).fetchall()

    db.close()

    return jsonify([
        {
            "id": "upload_" + str(row["id"]),
            "title": row["caption"] or row["title"],
            "filename": row["title"],
            "url": row["url"],
            "creator": (
                row["creator"].split("@")[0]
                if row["creator"]
                else "ticktock"
            ),
            "creator_uid": row["creator_uid"],
            "creator_gender": row["creator_gender"],
            "creator_photo": row["creator_photo"],
            "creator_followers": row["creator_followers"] or 0,
            "is_following": bool(row["is_following"]),
            "tags": row["tags"] or "",
            "created_at": row["created_at"],
            "source": row["source"]
        }
        for row in rows
    ])


# =========================================================
# SERVE UPLOADED VIDEOS
# =========================================================

@app.route(
    "/uploads/<filename>"
)
def uploaded_video(filename):

    return send_from_directory(
        UPLOAD_FOLDER,
        filename
    )


# =========================================================
# SWITCH ACCOUNT
# =========================================================

@app.route("/switch-account")
def switch_account():
    session.clear()
    response = redirect(url_for("login"))
    response.set_cookie(FORCE_OTP_COOKIE, "1", max_age=300, httponly=True, secure=True, samesite="Lax")
    return response


# =========================================================
# PASSWORD RESET
# =========================================================

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("forgot_password.html")

    email = request.form.get("username", "").strip().lower()
    if not email:
        return render_template("forgot_password.html", error="Enter your registered Gmail address.")
    if not re.fullmatch(r"[^@\s]+@gmail\.com", email):
        return render_template("forgot_password.html", error="Please enter the Gmail address you used to register.", entered_email=email)

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE lower(username)=?", (email,)).fetchone()
    db.close()

    # Give a clear message for a genuinely unknown account so a typo is easy to fix.
    if not user:
        return render_template(
            "forgot_password.html",
            error="This Gmail is not registered on Tick Tock ❌ Check the username/email and try again.",
            entered_email=email
        )

    otp = generate_otp()
    session["reset_otp_hash"] = hash_otp(otp)
    session["reset_otp_expires"] = time.time() + OTP_EXPIRY_SECONDS
    session["reset_otp_attempts"] = 0
    session["reset_user_id"] = user["id"]
    session["reset_email"] = user["username"]

    if not send_otp_email(user["username"], otp):
        for k in ("reset_otp_hash", "reset_otp_expires", "reset_otp_attempts", "reset_user_id", "reset_email"):
            session.pop(k, None)
        return render_template(
            "forgot_password.html",
            error="Your account was found, but the reset email could not be sent. Please try again.",
            entered_email=email
        )

    return render_template("reset_password.html", email=user["username"])


@app.route("/resend-reset-otp", methods=["POST"])
def resend_reset_otp():
    email = session.get("reset_email")
    user_id = session.get("reset_user_id")
    if not email or not user_id:
        return redirect(url_for("forgot_password"))

    db = get_db()
    user = db.execute("SELECT id, username FROM users WHERE id=? AND lower(username)=?", (user_id, email.lower())).fetchone()
    db.close()
    if not user:
        for k in ("reset_otp_hash", "reset_otp_expires", "reset_otp_attempts", "reset_user_id", "reset_email"):
            session.pop(k, None)
        return render_template("forgot_password.html", error="Account could not be found. Please enter your registered Gmail again.")

    otp = generate_otp()
    session["reset_otp_hash"] = hash_otp(otp)
    session["reset_otp_expires"] = time.time() + OTP_EXPIRY_SECONDS
    session["reset_otp_attempts"] = 0
    if not send_otp_email(email, otp):
        return render_template("reset_password.html", email=email, error="Could not resend OTP. Please try again.")
    return render_template("reset_password.html", email=email, message="New OTP sent 📩")


@app.route("/reset-password", methods=["POST"])
def reset_password():
    email = session.get("reset_email")
    user_id = session.get("reset_user_id")
    if not email or not user_id:
        return redirect(url_for("forgot_password"))

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=? AND lower(username)=?", (user_id, email.lower())).fetchone()
    db.close()
    if not user:
        for k in ("reset_otp_hash", "reset_otp_expires", "reset_otp_attempts", "reset_user_id", "reset_email"):
            session.pop(k, None)
        return render_template("forgot_password.html", error="Account could not be found. Please enter your registered Gmail again.")

    otp = request.form.get("otp", "").strip()
    new_password = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    if time.time() > session.get("reset_otp_expires", 0):
        return render_template("reset_password.html", email=email, error="OTP expired ❌ Please request a new OTP.")

    if not otp.isdigit() or len(otp) != 6:
        return render_template("reset_password.html", email=email, error="Enter the 6-digit OTP ❌")

    if hash_otp(otp) != session.get("reset_otp_hash"):
        attempts = session.get("reset_otp_attempts", 0) + 1
        session["reset_otp_attempts"] = attempts
        if attempts >= OTP_MAX_ATTEMPTS:
            session["reset_otp_expires"] = time.time()
            return render_template("reset_password.html", email=email, error="Too many wrong OTP attempts ❌ Request a new OTP.")
        return render_template("reset_password.html", email=email, error=f"Wrong OTP ❌ {OTP_MAX_ATTEMPTS - attempts} attempt(s) remaining.")

    if not valid_password(new_password):
        return render_template("reset_password.html", email=email, error="Please enter a password.")
    if new_password != confirm:
        return render_template("reset_password.html", email=email, error="Passwords do not match ❌")

    db = get_db()
    db.execute("UPDATE users SET password=?, email_verified=1 WHERE id=?", (generate_password_hash(new_password), user_id))
    db.commit()
    db.close()

    token = _issue_trusted_device(user_id)
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    db.close()
    for k in ("reset_otp_hash", "reset_otp_expires", "reset_otp_attempts", "reset_user_id", "reset_email"):
        session.pop(k, None)
    _start_user_session(user)
    response = redirect(url_for("home" if user["profile_complete"] else "profile_setup"))
    return _set_trusted_cookie(response, token)


# =========================================================
# DIAMONDS / WALLET / GIFTS
# =========================================================

DIAMOND_PACKS = {
    "starter": {"rupees": 49, "diamonds": 50},
    "popular": {"rupees": 99, "diamonds": 110},
    "creator": {"rupees": 199, "diamonds": 240},
    "pro": {"rupees": 499, "diamonds": 650},
}

GIFT_CATALOG = {
    "heart": {"name": "Heart", "diamonds": 5, "emoji": "❤️"},
    "rose": {"name": "Rose", "diamonds": 20, "emoji": "🌹"},
    "fire": {"name": "Fire", "diamonds": 50, "emoji": "🔥"},
    "crown": {"name": "Crown", "diamonds": 100, "emoji": "👑"},
}

def ensure_wallet(user_id):
    db = get_db()
    db.execute("INSERT INTO diamond_wallets (user_id, balance) VALUES (?, 0)", (user_id,))
    db.commit()
    row = db.execute("SELECT balance FROM diamond_wallets WHERE user_id=?", (user_id,)).fetchone()
    db.close()
    return int(row["balance"] if row else 0)


@app.route("/api/diamonds")
def diamond_wallet():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Login required."}), 401
    balance = ensure_wallet(session["user_id"])
    db = get_db()
    tx = db.execute("SELECT type, amount, description, created_at FROM diamond_transactions WHERE user_id=? ORDER BY id DESC LIMIT 20", (session["user_id"],)).fetchall()
    db.close()
    return jsonify({"success": True, "balance": balance, "packs": DIAMOND_PACKS, "gifts": GIFT_CATALOG, "transactions": [dict(x) for x in tx]})


@app.route("/api/diamonds/create-order", methods=["POST"])
def create_diamond_order():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Login required."}), 401
    data = request.get_json(silent=True) or {}
    pack_id = str(data.get("pack", "")).strip()
    pack = DIAMOND_PACKS.get(pack_id)
    if not pack:
        return jsonify({"success": False, "message": "Invalid diamond pack."}), 400

    key_id = os.environ.get("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id or not key_secret:
        return jsonify({"success": False, "message": "Top Up is ready, but Razorpay payment keys are not configured yet."}), 503

    try:
        r = requests.post(
            "https://api.razorpay.com/v1/orders",
            auth=(key_id, key_secret),
            json={"amount": pack["rupees"] * 100, "currency": "INR", "receipt": f"tt-{session['user_id']}-{int(time.time())}", "notes": {"user_id": str(session["user_id"]), "diamonds": str(pack["diamonds"]) }},
            timeout=20,
        )
        if not r.ok:
            return jsonify({"success": False, "message": "Payment order could not be created."}), 502
        order = r.json()
        return jsonify({"success": True, "key_id": key_id, "order_id": order["id"], "amount": order["amount"], "currency": order["currency"], "diamonds": pack["diamonds"]})
    except Exception as e:
        print("Razorpay order error:", e)
        return jsonify({"success": False, "message": "Payment service is temporarily unavailable."}), 503


@app.route("/api/diamonds/verify", methods=["POST"])
def verify_diamond_payment():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Login required."}), 401
    data = request.get_json(silent=True) or {}
    order_id = str(data.get("razorpay_order_id", ""))
    payment_id = str(data.get("razorpay_payment_id", ""))
    signature = str(data.get("razorpay_signature", ""))
    diamonds = int(data.get("diamonds", 0) or 0)
    if not order_id or not payment_id or not signature or diamonds <= 0:
        return jsonify({"success": False, "message": "Invalid payment details."}), 400
    secret = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
    expected = hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return jsonify({"success": False, "message": "Payment verification failed."}), 400

    db = get_db()
    existing = db.execute("SELECT id FROM diamond_transactions WHERE provider_order_id=?", (order_id,)).fetchone()
    if existing:
        row = db.execute("SELECT balance FROM diamond_wallets WHERE user_id=?", (session["user_id"],)).fetchone()
        db.close()
        return jsonify({"success": True, "balance": int(row["balance"] if row else 0), "message": "Payment already applied."})
    db.execute("INSERT INTO diamond_wallets (user_id, balance) VALUES (?, 0)", (session["user_id"],))
    db.execute("UPDATE diamond_wallets SET balance=balance+?, updated_at=CURRENT_TIMESTAMP WHERE user_id=?", (diamonds, session["user_id"]))
    db.execute("INSERT INTO diamond_transactions (user_id, type, amount, description, provider_order_id) VALUES (?, 'topup', ?, ?, ?)", (session["user_id"], diamonds, f"Top Up: {diamonds} diamonds", order_id))
    db.commit()
    row = db.execute("SELECT balance FROM diamond_wallets WHERE user_id=?", (session["user_id"],)).fetchone()
    db.close()
    return jsonify({"success": True, "balance": int(row["balance"]), "message": f"{diamonds} diamonds added 💎"})


@app.route("/api/gifts/send", methods=["POST"])
def send_gift():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Login required."}), 401
    data = request.get_json(silent=True) or {}
    uid = str(data.get("uid", "")).strip()
    gift_id = str(data.get("gift", "")).strip()
    video_id = str(data.get("video_id", "")).strip() or None
    gift = GIFT_CATALOG.get(gift_id)
    if not uid or not gift:
        return jsonify({"success": False, "message": "Choose a valid gift."}), 400
    db = get_db()
    receiver = db.execute("SELECT id, username FROM users WHERE uid=?", (uid,)).fetchone()
    if not receiver:
        db.close(); return jsonify({"success": False, "message": "Creator not found."}), 404
    if receiver["id"] == session["user_id"]:
        db.close(); return jsonify({"success": False, "message": "You cannot gift yourself."}), 400
    db.execute("INSERT INTO diamond_wallets (user_id, balance) VALUES (?, 0)", (session["user_id"],))
    db.execute("INSERT INTO diamond_wallets (user_id, balance) VALUES (?, 0)", (receiver["id"],))
    cur = db.execute("UPDATE diamond_wallets SET balance=balance-?, updated_at=CURRENT_TIMESTAMP WHERE user_id=? AND balance>=?", (gift["diamonds"], session["user_id"], gift["diamonds"]))
    if getattr(cur, "rowcount", 0) != 1:
        db.rollback(); db.close(); return jsonify({"success": False, "message": "Not enough diamonds 💎 Top Up to send this gift."}), 400
    db.execute("UPDATE diamond_wallets SET balance=balance+?, updated_at=CURRENT_TIMESTAMP WHERE user_id=?", (gift["diamonds"], receiver["id"]))
    db.execute("INSERT INTO diamond_transactions (user_id, type, amount, description) VALUES (?, 'gift_sent', ?, ?)", (session["user_id"], -gift["diamonds"], f"Sent {gift['name']} to {receiver['username']}"))
    db.execute("INSERT INTO diamond_transactions (user_id, type, amount, description) VALUES (?, 'gift_received', ?, ?)", (receiver["id"], gift["diamonds"], f"Received {gift['name']}"))
    db.execute("INSERT INTO gifts (sender_id, receiver_id, video_id, gift_name, diamonds) VALUES (?, ?, ?, ?, ?)", (session["user_id"], receiver["id"], video_id, gift["name"], gift["diamonds"]))
    db.commit()
    row = db.execute("SELECT balance FROM diamond_wallets WHERE user_id=?", (session["user_id"],)).fetchone()
    db.close()
    return jsonify({"success": True, "balance": int(row["balance"]), "message": f"{gift['emoji']} {gift['name']} sent!"})


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    print("")

    print(
        "=============================="
    )

    print(
        "        TICK TOCK 🤖"
    )

    print(
        "=============================="
    )

    print(
        "Login: "
        "http://127.0.0.1:5000/login"
    )

    print(
        "=============================="
    )

    print("")

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )