from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    send_from_directory,
    make_response
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
from concurrent.futures import ThreadPoolExecutor, as_completed

from email.message import EmailMessage
import smtplib

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from werkzeug.utils import secure_filename


app = Flask(
    __name__,
    template_folder="templates"
)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "tick-tock-secret-key"
)


# =========================================================
# EMAIL OTP SETTINGS
# =========================================================

OTP_EXPIRY_SECONDS = 3 * 60
OTP_MAX_ATTEMPTS = 3
OTP_LOCK_SECONDS = 5 * 60


def generate_otp():
    return str(
        random.randint(100000, 999999)
    )


def hash_otp(otp):
    return hashlib.sha256(
        otp.encode("utf-8")
    ).hexdigest()


def send_otp_email(to_email, otp):

    smtp_host = os.environ.get(
        "SMTP_HOST",
        "smtp.gmail.com"
    )

    smtp_port = int(
        os.environ.get(
            "SMTP_PORT",
            "587"
        )
    )

    smtp_user = os.environ.get(
        "SMTP_USER"
    )

    smtp_password = os.environ.get(
        "SMTP_PASSWORD"
    )

    if not smtp_user or not smtp_password:
        print(
            "SMTP credentials are missing."
        )
        return False

    message = EmailMessage()

    message["Subject"] = (
        "Tick Tock Login OTP"
    )

    message["From"] = smtp_user

    message["To"] = to_email

    message.set_content(
        f"""Hello,

Your Tick Tock login OTP is:

{otp}

This OTP expires in 3 minutes.

If you did not request this OTP,
please ignore this email.

Tick Tock ❤️
"""
    )

    try:

        with smtplib.SMTP(
            smtp_host,
            smtp_port,
            timeout=20
        ) as server:

            server.starttls()

            server.login(
                smtp_user,
                smtp_password
            )

            server.send_message(
                message
            )

        print(
            "OTP sent successfully to:",
            to_email
        )

        return True

    except Exception as error:

        print(
            "OTP email error:",
            error
        )

        return False


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

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

DB_FILE = os.path.join(
    BASE_DIR,
    "ticktock.db"
)

UPLOAD_FOLDER = os.path.join(
    BASE_DIR,
    "uploads"
)

os.makedirs(
    UPLOAD_FOLDER,
    exist_ok=True
)

app.config["UPLOAD_FOLDER"] = (
    UPLOAD_FOLDER
)

app.config["MAX_CONTENT_LENGTH"] = (
    100 * 1024 * 1024
)


def get_db():

    db = sqlite3.connect(
        DB_FILE
    )

    db.row_factory = sqlite3.Row

    return db


def column_exists(
    db,
    table,
    column
):

    columns = db.execute(
        f"PRAGMA table_info({table})"
    ).fetchall()

    return any(
        row["name"] == column
        for row in columns
    )


def add_column_if_missing(
    db,
    table,
    column,
    definition
):

    if not column_exists(
        db,
        table,
        column
    ):

        db.execute(
            f"""
            ALTER TABLE {table}
            ADD COLUMN {column}
            {definition}
            """
        )


def create_uid(db):

    while True:

        uid = "".join(
            random.choices(string.digits, k=10)
        )

        found = db.execute(
            "SELECT id FROM users WHERE uid=?",
            (uid,)
        ).fetchone()

        if not found:
            return uid


def init_db():

    db = get_db()

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (

            id INTEGER
            PRIMARY KEY
            AUTOINCREMENT,

            username TEXT
            UNIQUE NOT NULL,

            password TEXT
            NOT NULL,

            uid TEXT
            UNIQUE,

            gender TEXT,

            age INTEGER,

            photo TEXT,

            bio TEXT,

            location TEXT,

            profile_complete INTEGER
            DEFAULT 0,

            created_at TIMESTAMP
            DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    add_column_if_missing(
        db,
        "users",
        "uid",
        "TEXT"
    )

    add_column_if_missing(
        db,
        "users",
        "gender",
        "TEXT"
    )

    add_column_if_missing(
        db,
        "users",
        "age",
        "INTEGER"
    )

    add_column_if_missing(
        db,
        "users",
        "photo",
        "TEXT"
    )

    add_column_if_missing(
        db,
        "users",
        "bio",
        "TEXT"
    )

    add_column_if_missing(
        db,
        "users",
        "location",
        "TEXT"
    )

    add_column_if_missing(
        db,
        "users",
        "phone",
        "TEXT"
    )

    add_column_if_missing(
        db,
        "users",
        "privacy",
        "TEXT DEFAULT 'public'"
    )

    add_column_if_missing(
        db,
        "users",
        "latitude",
        "REAL"
    )

    add_column_if_missing(
        db,
        "users",
        "longitude",
        "REAL"
    )

    add_column_if_missing(
        db,
        "users",
        "last_seen",
        "TIMESTAMP"
    )

    add_column_if_missing(
        db,
        "users",
        "last_seen_privacy",
        "TEXT DEFAULT 'public'"
    )

    add_column_if_missing(
        db,
        "users",
        "profile_complete",
        "INTEGER DEFAULT 0"
    )

    users_to_refresh = db.execute(
        """
        SELECT id, uid
        FROM users
        WHERE uid IS NULL
           OR uid=''
           OR length(uid) != 10
           OR uid GLOB '*[^0-9]*'
        """
    ).fetchall()

    # Move old UIDs out of the UNIQUE column first, then assign
    # fresh 10-digit numeric UIDs.
    for user in users_to_refresh:
        db.execute(
            "UPDATE users SET uid=? WHERE id=?",
            ("OLD-" + str(user["id"]), user["id"])
        )

    for user in users_to_refresh:
        db.execute(
            "UPDATE users SET uid=? WHERE id=?",
            (create_uid(db), user["id"])
        )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS videos (

            id INTEGER
            PRIMARY KEY
            AUTOINCREMENT,

            title TEXT
            NOT NULL,

            url TEXT
            NOT NULL,

            creator TEXT
            NOT NULL,

            source TEXT
            NOT NULL
        )
        """
    )

    add_column_if_missing(db, "videos", "caption", "TEXT")
    add_column_if_missing(db, "videos", "tags", "TEXT")
    add_column_if_missing(db, "videos", "privacy", "TEXT DEFAULT 'public'")
    add_column_if_missing(db, "videos", "user_id", "INTEGER")

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS likes (

            id INTEGER
            PRIMARY KEY
            AUTOINCREMENT,

            user_id INTEGER
            NOT NULL,

            video_id TEXT
            NOT NULL,

            UNIQUE(
                user_id,
                video_id
            )
        )
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS comments (

            id INTEGER
            PRIMARY KEY
            AUTOINCREMENT,

            user_id INTEGER
            NOT NULL,

            video_id TEXT
            NOT NULL,

            comment TEXT
            NOT NULL,

            created_at TIMESTAMP
            DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS shares (

            id INTEGER
            PRIMARY KEY
            AUTOINCREMENT,

            user_id INTEGER
            NOT NULL,

            video_id TEXT
            NOT NULL,

            created_at TIMESTAMP
            DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(
                user_id,
                video_id
            )
        )
        """
    )

    db.execute("""
        CREATE TABLE IF NOT EXISTS saved_videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            video_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, video_id)
        )
    """)

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS friend_requests (

            id INTEGER
            PRIMARY KEY
            AUTOINCREMENT,

            sender_id INTEGER
            NOT NULL,

            receiver_id INTEGER
            NOT NULL,

            status TEXT
            DEFAULT 'pending',

            created_at TIMESTAMP
            DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(
                sender_id,
                receiver_id
            )
        )
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS friends (

            id INTEGER
            PRIMARY KEY
            AUTOINCREMENT,

            user1_id INTEGER
            NOT NULL,

            user2_id INTEGER
            NOT NULL,

            created_at TIMESTAMP
            DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(
                user1_id,
                user2_id
            )
        )
        """
    )

    db.execute("""
        CREATE TABLE IF NOT EXISTS follows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            follower_id INTEGER NOT NULL,
            following_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(follower_id, following_id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            actor_id INTEGER,
            type TEXT NOT NULL,
            video_id TEXT,
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            owner_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS group_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(group_id, user_id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS group_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    add_column_if_missing(db, "users", "diamonds", "INTEGER DEFAULT 0")
    add_column_if_missing(db, "users", "membership", "INTEGER DEFAULT 0")
    add_column_if_missing(db, "users", "membership_until", "TIMESTAMP")

    db.execute("""
        CREATE TABLE IF NOT EXISTS diamond_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            rupees INTEGER NOT NULL,
            diamonds INTEGER NOT NULL,
            order_type TEXT NOT NULL DEFAULT 'topup',
            status TEXT NOT NULL DEFAULT 'pending',
            txn_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS blocks (

            id INTEGER
            PRIMARY KEY
            AUTOINCREMENT,

            blocker_id INTEGER
            NOT NULL,

            blocked_id INTEGER
            NOT NULL,

            created_at TIMESTAMP
            DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(
                blocker_id,
                blocked_id
            )
        )
        """
    )

    db.execute("""
        CREATE TABLE IF NOT EXISTS login_devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()

    db.close()


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

    if len(password) < 8:
        return False

    if not re.search(
        r"[A-Z]",
        password
    ):
        return False

    if not re.search(
        r"[a-z]",
        password
    ):
        return False

    if not re.search(
        r"[0-9]",
        password
    ):
        return False

    if not re.search(
        r"[^A-Za-z0-9]",
        password
    ):
        return False

    return True


def create_notification(db, user_id, actor_id, ntype, message, video_id=None):
    if user_id == actor_id:
        return
    db.execute("""
        INSERT INTO notifications
        (user_id, actor_id, type, video_id, message)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, actor_id, ntype, video_id, message))


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
        photo=user["photo"]
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
                "Password needs 8+ "
                "characters, uppercase, "
                "lowercase, number and "
                "special character."
            ),
            entered_email=email
        )

    db = get_db()

    existing = db.execute(
        """
        SELECT id
        FROM users
        WHERE username=?
        """,
        (email,)
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

    password_hash = (
        generate_password_hash(
            password
        )
    )

    cursor = db.execute(
        """
        INSERT INTO users
        (
            username,
            password,
            uid,
            profile_complete
        )
        VALUES (?, ?, ?, 0)
        """,
        (
            email,
            password_hash,
            uid
        )
    )

    user_id = cursor.lastrowid

    db.commit()

    db.close()

    # The account is created and the user is
    # immediately signed in for profile setup.
    session["user_id"] = user_id
    session["username"] = email
    session["uid"] = uid

    return redirect(
        url_for("profile_setup")
    )


# =========================================================
# TRUSTED DEVICE LOGIN
# =========================================================

TRUSTED_DEVICE_COOKIE = "ticktock_device"
TRUSTED_DEVICE_DAYS = 30


def hash_device_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_trusted_device(user_id):
    token = request.cookies.get(TRUSTED_DEVICE_COOKIE)
    if not token:
        return None
    token_hash = hash_device_token(token)
    db = get_db()
    row = db.execute(
        """
        SELECT id, user_id, expires_at
        FROM login_devices
        WHERE user_id=? AND token_hash=? AND expires_at>?
        """,
        (user_id, token_hash, time.time())
    ).fetchone()
    db.close()
    return row


def issue_trusted_device(user_id):
    token = secrets.token_urlsafe(48)
    token_hash = hash_device_token(token)
    expires = time.time() + TRUSTED_DEVICE_DAYS * 86400
    db = get_db()
    db.execute(
        """
        INSERT INTO login_devices(user_id, token_hash, expires_at)
        VALUES(?,?,?)
        """,
        (user_id, token_hash, expires)
    )
    db.commit()
    db.close()
    return token


def finish_login(user):
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["uid"] = user["uid"]
    if not user["profile_complete"]:
        return redirect(url_for("profile_setup"))
    return redirect(url_for("home"))


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
    user = db.execute(
        "SELECT * FROM users WHERE username=?",
        (email,)
    ).fetchone()
    db.close()

    if not user:
        return render_template(
            "login.html",
            error="Gmail is not registered ❌ Please check the Gmail or register first.",
            register_required=True,
            entered_email=email
        )

    if not check_password_hash(user["password"], password):
        return render_template(
            "login.html",
            error="Wrong password ❌ You can reset your password below.",
            show_forgot=True,
            entered_email=email
        )

    # Normal login on a previously trusted browser/device: no OTP.
    trusted = get_trusted_device(user["id"])
    if trusted:
        db = get_db()
        db.execute(
            "UPDATE login_devices SET last_seen=CURRENT_TIMESTAMP WHERE id=?",
            (trusted["id"],)
        )
        db.commit()
        db.close()
        clear_otp_session()
        return finish_login(user)

    # New browser/device: require OTP once, then trust this device for 30 days.
    otp = generate_otp()
    session["otp_hash"] = hash_otp(otp)
    session["otp_expires"] = time.time() + OTP_EXPIRY_SECONDS
    session["otp_attempts"] = 0
    session["otp_locked_until"] = 0
    session["otp_user_id"] = user["id"]
    session["otp_email"] = email

    sent = send_otp_email(email, otp)

    if not sent:
        # Keep local development usable if SMTP is not configured.
        clear_otp_session()
        return finish_login(user)

    return render_template(
        "login.html",
        otp_required=True,
        entered_email=email,
        otp_message="New device/login detected. OTP sent to your Gmail 📩"
    )


def clear_reset_session():
    for key in (
        "reset_otp_hash",
        "reset_otp_expires",
        "reset_otp_attempts",
        "reset_otp_locked_until",
        "reset_user_id",
        "reset_email",
    ):
        session.pop(key, None)



# =========================================================
# PASSWORD RESET
# =========================================================

def send_reset_otp_email(to_email, otp):
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")

    if not smtp_user or not smtp_password:
        print("SMTP credentials are missing for password reset.")
        return False

    message = EmailMessage()
    message["Subject"] = "Tick Tock Password Reset OTP"
    message["From"] = smtp_user
    message["To"] = to_email
    message.set_content(
        f"""Hello,

Your Tick Tock password reset OTP is:

{otp}

This OTP expires in 3 minutes.
You have 3 attempts. After 3 wrong attempts, wait 5 minutes.

If you did not request a password reset, please ignore this email.

Tick Tock ❤️
"""
    )

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(message)
        return True
    except Exception as error:
        print("Password reset email error:", error)
        return False


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("forgot_password.html")

    email = request.form.get("username", "").strip().lower()

    if not email.endswith("@gmail.com"):
        return render_template(
            "forgot_password.html",
            error="Please enter your registered Gmail address."
        )

    db = get_db()
    user = db.execute(
        "SELECT id, username FROM users WHERE username=?",
        (email,)
    ).fetchone()
    db.close()

    if not user:
        return render_template(
            "forgot_password.html",
            error="This Gmail is not registered. Please register first."
        )

    otp = generate_otp()

    session["reset_otp_hash"] = hash_otp(otp)
    session["reset_otp_expires"] = time.time() + (3 * 60)
    session["reset_otp_attempts"] = 0
    session["reset_otp_locked_until"] = 0
    session["reset_user_id"] = user["id"]
    session["reset_email"] = email

    if not send_reset_otp_email(email, otp):
        clear_reset_session()
        return render_template(
            "forgot_password.html",
            error="OTP could not be sent. Configure Gmail SMTP/App Password first."
        )

    return render_template(
        "reset_password.html",
        email=email
    )


@app.route("/reset-password", methods=["POST"])
def reset_password():
    if "reset_user_id" not in session:
        return redirect(url_for("forgot_password"))

    now = time.time()
    locked_until = session.get("reset_otp_locked_until", 0)

    if now < locked_until:
        remaining = int(locked_until - now)
        return render_template(
            "reset_password.html",
            email=session.get("reset_email", ""),
            error=f"Too many wrong attempts ❌ Try again in {remaining // 60}m {remaining % 60}s."
        )

    if now > session.get("reset_otp_expires", 0):
        clear_reset_session()
        return render_template(
            "forgot_password.html",
            error="OTP expired ❌ Please request a new reset OTP."
        )

    otp = request.form.get("otp", "").strip()
    new_password = request.form.get("password", "")

    if hash_otp(otp) != session.get("reset_otp_hash"):
        attempts = session.get("reset_otp_attempts", 0) + 1
        session["reset_otp_attempts"] = attempts

        if attempts >= 3:
            session["reset_otp_locked_until"] = time.time() + (5 * 60)
            return render_template(
                "reset_password.html",
                email=session.get("reset_email", ""),
                error="3 wrong OTP attempts ❌ Please wait 5 minutes."
            )

        return render_template(
            "reset_password.html",
            email=session.get("reset_email", ""),
            error=f"Wrong OTP ❌ {3 - attempts} attempt(s) remaining."
        )

    if not valid_password(new_password):
        return render_template(
            "reset_password.html",
            email=session.get("reset_email", ""),
            error="Password needs 8+ characters, uppercase, lowercase, number and special character."
        )

    db = get_db()
    db.execute(
        "UPDATE users SET password=? WHERE id=?",
        (generate_password_hash(new_password), session["reset_user_id"])
    )
    db.commit()
    db.close()

    clear_reset_session()

    return render_template(
        "login.html",
        success="Password reset successfully ✅ Please login with your new password."
    )


@app.route("/resend-reset-otp", methods=["POST"])
def resend_reset_otp():
    if "reset_user_id" not in session:
        return redirect(url_for("forgot_password"))

    otp = generate_otp()
    email = session.get("reset_email", "")

    session["reset_otp_hash"] = hash_otp(otp)
    session["reset_otp_expires"] = time.time() + (3 * 60)
    session["reset_otp_attempts"] = 0
    session["reset_otp_locked_until"] = 0

    if not send_reset_otp_email(email, otp):
        return render_template(
            "reset_password.html",
            email=email,
            error="Could not resend OTP. Please try again."
        )

    return render_template(
        "reset_password.html",
        email=email,
        error="New OTP sent 📩"
    )


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

    clear_otp_session()

    response = finish_login(user)

    # Remember this browser/device for 30 days.
    token = issue_trusted_device(user["id"])
    response.set_cookie(
        TRUSTED_DEVICE_COOKIE,
        token,
        max_age=TRUSTED_DEVICE_DAYS * 86400,
        httponly=True,
        secure=request.is_secure,
        samesite="Lax",
    )
    return response


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

@app.route(
    "/profile-setup",
    methods=["GET", "POST"]
)
def profile_setup():

    if not logged_in():

        return redirect(
            url_for("login")
        )

    if request.method == "GET":

        db = get_db()

        user = db.execute(
            """
            SELECT
                uid,
                gender,
                age,
                photo,
                bio,
                location,
                phone,
                privacy,
                latitude,
                longitude,
                last_seen_privacy
            FROM users
            WHERE id=?
            """,
            (session["user_id"],)
        ).fetchone()

        db.close()

        return render_template(
            "profile.html",
            uid=session.get("uid"),
            user=dict(user) if user else {}
        )

    gender = request.form.get(
        "gender",
        ""
    ).strip()

    age_text = request.form.get(
        "age",
        ""
    ).strip()

    bio = request.form.get(
        "bio",
        ""
    ).strip()

    location = request.form.get(
        "location",
        ""
    ).strip()

    phone = request.form.get(
        "phone",
        ""
    ).strip()

    privacy = request.form.get(
        "privacy",
        "public"
    ).strip().lower()

    last_seen_privacy = request.form.get(
        "last_seen_privacy",
        "public"
    ).strip().lower()
    if last_seen_privacy not in ("public", "private"):
        last_seen_privacy = "public"

    latitude_text = request.form.get(
        "latitude",
        ""
    ).strip()

    longitude_text = request.form.get(
        "longitude",
        ""
    ).strip()

    if privacy not in ("public", "private"):

        privacy = "public"

    try:

        age = int(age_text)

    except (ValueError, TypeError):

        return render_template(
            "profile.html",
            uid=session.get("uid"),
            user={},
            error="Enter a valid age."
        )

    if age < 16 or age > 100:

        return render_template(
            "profile.html",
            uid=session.get("uid"),
            user={},
            error="Age must be between 16 and 100."
        )

    latitude = None
    longitude = None

    if latitude_text and longitude_text:

        try:

            latitude = float(latitude_text)
            longitude = float(longitude_text)

            if not (-90 <= latitude <= 90):
                latitude = None

            if not (-180 <= longitude <= 180):
                longitude = None

        except ValueError:

            latitude = None
            longitude = None

    photo = request.files.get("profile_photo") or request.files.get("photo")

    photo_filename = None

    if photo and photo.filename:

        extension = os.path.splitext(
            photo.filename
        )[1].lower()

        allowed = {
            ".jpg",
            ".jpeg",
            ".png",
            ".webp"
        }

        if extension not in allowed:

            return render_template(
                "profile.html",
                uid=session.get("uid"),
                user={},
                error="Use JPG, PNG or WEBP."
            )

        photo_filename = (
            "profile_"
            +
            str(session["user_id"])
            +
            extension
        )

        photo.save(
            os.path.join(
                UPLOAD_FOLDER,
                photo_filename
            )
        )

    db = get_db()

    if photo_filename:

        db.execute(
            """
            UPDATE users
            SET
                gender=?,
                age=?,
                photo=?,
                bio=?,
                location=?,
                phone=?,
                privacy=?,
                latitude=?,
                longitude=?,
                last_seen_privacy=?,
                profile_complete=1
            WHERE id=?
            """,
            (
                gender,
                age,
                photo_filename,
                bio,
                location,
                phone,
                privacy,
                latitude,
                longitude,
                last_seen_privacy,
                session["user_id"]
            )
        )

    else:

        db.execute(
            """
            UPDATE users
            SET
                gender=?,
                age=?,
                bio=?,
                location=?,
                phone=?,
                privacy=?,
                latitude=?,
                longitude=?,
                last_seen_privacy=?,
                profile_complete=1
            WHERE id=?
            """,
            (
                gender,
                age,
                bio,
                location,
                phone,
                privacy,
                latitude,
                longitude,
                last_seen_privacy,
                session["user_id"]
            )
        )

    db.commit()
    db.close()

    # Follow feature will be added later.
    # For now, show a simple skip page and then open Reels.
    return redirect(
        url_for("follow_setup")
    )


# =========================================================
# FOLLOW PEOPLE SETUP
# =========================================================

@app.route(
    "/follow-setup",
    methods=["GET", "POST"]
)
def follow_setup():

    if not logged_in():

        return redirect(
            url_for("login")
        )

    if request.method == "POST":

        return redirect(
            url_for("home")
        )

    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport"
              content="width=device-width, initial-scale=1">
        <title>Tick Tock</title>
        <style>
            body {
                margin: 0;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                background: #080808;
                color: white;
                font-family: Arial, sans-serif;
            }
            .box {
                width: 90%;
                max-width: 430px;
                text-align: center;
                padding: 35px 25px;
                border-radius: 24px;
                background: #171717;
                box-sizing: border-box;
            }
            h1 { margin-bottom: 12px; }
            p { color: #bbb; line-height: 1.5; }
            button {
                width: 100%;
                padding: 15px;
                margin-top: 20px;
                border: 0;
                border-radius: 14px;
                background: white;
                color: black;
                font-size: 17px;
                font-weight: bold;
                cursor: pointer;
            }
        </style>
    </head>
    <body>
        <div class="box">
            <h1>👥 Follow People</h1>
            <p>
                Find people you like and follow them.
                The follow feature will be added soon.
            </p>
            <form method="POST">
                <button type="submit">
                    Skip for now → Watch Reels
                </button>
            </form>
        </div>
    </body>
    </html>
    """


# =========================================================
# MY PROFILE API
# =========================================================

def touch_last_seen():
    if not logged_in():
        return
    try:
        db = get_db()
        db.execute("UPDATE users SET last_seen=CURRENT_TIMESTAMP WHERE id=?", (session["user_id"],))
        db.commit()
        db.close()
    except Exception:
        pass


@app.before_request
def update_last_seen():
    if request.path.startswith("/api/") or request.path in ("/home", "/profile", "/profile-setup"):
        touch_last_seen()


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
            gender,
            age,
            photo,
            bio,
            location,
            phone,
            privacy,
            last_seen_privacy
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
            gender,
            age,
            photo,
            bio,
            location,
            phone,
            privacy
        FROM users
        WHERE uid=?
        """,
        (
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
        WHERE uid=?
        """,
        (
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

    actor=db.execute("SELECT username FROM users WHERE id=?",(sender,)).fetchone()
    name=(actor["username"] or "Someone").split("@")[0]
    create_notification(db, receiver, sender, "friend_request", f"@{name} sent you a friend request")

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
        INSERT OR IGNORE INTO friends
        (
            user1_id,
            user2_id
        )
        VALUES (?, ?)
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
        WHERE uid=?
        """,
        (
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
        WHERE uid=?
        """,
        (
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
        INSERT OR IGNORE INTO blocks
        (
            blocker_id,
            blocked_id
        )
        VALUES (?, ?)
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
        WHERE uid=?
        """,
        (
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
# NOTIFICATIONS
# =========================================================

@app.route("/api/notifications")
def get_notifications():
    if not logged_in(): return jsonify([]),401
    db=get_db(); me=session["user_id"]
    rows=db.execute("""
        SELECT n.id,n.type,n.message,n.video_id,n.is_read,n.created_at,
               u.username,u.uid,u.photo
        FROM notifications n
        LEFT JOIN users u ON u.id=n.actor_id
        WHERE n.user_id=?
        ORDER BY n.id DESC LIMIT 100
    """,(me,)).fetchall()
    unread=db.execute("SELECT COUNT(*) total FROM notifications WHERE user_id=? AND is_read=0",(me,)).fetchone()["total"]
    db.close()
    return jsonify({"notifications":[dict(r) for r in rows],"unread":unread})

@app.route("/api/notifications/read", methods=["POST"])
def read_notifications():
    if not logged_in(): return jsonify({"success":False}),401
    db=get_db(); db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?",(session["user_id"],)); db.commit(); db.close()
    return jsonify({"success":True})


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
VIDEO_CACHE_TIME = 0
VIDEO_CACHE_TTL = 15 * 60


def _pixabay_query(query):
    """Fetch one small, fast Pixabay result page."""
    if not PIXABAY_API_KEY:
        return []

    try:
        response = requests.get(
            PIXABAY_URL,
            params={
                "key": PIXABAY_API_KEY,
                "q": query,
                "per_page": 24,
                "video_type": "all",
                "safesearch": "true",
            },
            timeout=4,
        )
        if response.status_code != 200:
            return []

        output = []
        for item in response.json().get("hits", []):
            duration = int(item.get("duration", 9999) or 9999)
            if duration > 30:
                continue

            files = item.get("videos", {})
            selected = None

            # Small is intentionally first: faster startup on mobile/slow networks.
            for quality in ("small", "medium", "tiny", "large"):
                info = files.get(quality)
                if info and info.get("url"):
                    selected = info
                    break

            if not selected:
                continue

            output.append({
                "id": "pixabay_" + str(item.get("id")),
                "title": query.title() + " Reel",
                "url": selected["url"],
                "creator": item.get("user", "Creator"),
                "duration": duration,
                "source": "pixabay",
            })

        return output

    except Exception as error:
        print("Pixabay query error:", error)
        return []


def get_pixabay_videos(force=False):
    global VIDEO_CACHE, VIDEO_CACHE_TIME

    now = time.time()
    if VIDEO_CACHE and not force and now - VIDEO_CACHE_TIME < VIDEO_CACHE_TTL:
        result = VIDEO_CACHE.copy()
        random.shuffle(result)
        return result

    if not PIXABAY_API_KEY:
        print("PIXABAY_API_KEY missing.")
        return []

    queries = random.sample(SEARCHES, min(4, len(SEARCHES)))
    result = []

    # Fetch several searches at the same time instead of waiting 4 x sequential timeouts.
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_pixabay_query, q) for q in queries]
        for future in as_completed(futures):
            result.extend(future.result())

    unique = {}
    for video in result:
        unique[video["id"]] = video

    VIDEO_CACHE = list(unique.values())
    VIDEO_CACHE_TIME = time.time()
    random.shuffle(VIDEO_CACHE)

    print("Automatic Reels:", len(VIDEO_CACHE))
    return VIDEO_CACHE


def warm_reels_cache():
    try:
        get_pixabay_videos()
        print("Reels cache warmed successfully.")
    except Exception as error:
        print("Reels warm-up error:", error)


@app.route("/api/videos")
def api_videos():

    return jsonify(
        get_pixabay_videos()
    )


@app.route("/api/recommended-videos")
def recommended_videos():
    """Feed endpoint used by the home page."""
    try:
        return jsonify(get_pixabay_videos())
    except Exception as error:
        print("Recommended Reels error:", error)
        return jsonify([])


@app.route("/api/refresh", methods=["GET", "POST"])
def refresh_videos():

    global VIDEO_CACHE

    VIDEO_CACHE = []
    VIDEO_CACHE_TIME = 0

    return jsonify({
        "success": True,
        "videos": get_pixabay_videos(force=True)
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

        raw_video_id = str(video_id)
        if raw_video_id.startswith("upload_"):
            raw_video_id = raw_video_id[7:]
        video_owner = db.execute("SELECT user_id FROM videos WHERE CAST(id AS TEXT)=?", (raw_video_id,)).fetchone()
        if video_owner and video_owner["user_id"]:
            actor=db.execute("SELECT username FROM users WHERE id=?",(session["user_id"],)).fetchone()
            name=(actor["username"] or "Someone").split("@")[0]
            create_notification(db, video_owner["user_id"], session["user_id"], "like", f"@{name} liked your Reel", video_id)

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

    raw_video_id = str(video_id)[7:] if str(video_id).startswith("upload_") else str(video_id)
    owner = db.execute("SELECT user_id FROM videos WHERE CAST(id AS TEXT)=?", (raw_video_id,)).fetchone()
    if owner and owner["user_id"]:
        actor = db.execute("SELECT username FROM users WHERE id=?", (session["user_id"],)).fetchone()
        name = (actor["username"] or "Someone").split("@")[0]
        create_notification(db, owner["user_id"], session["user_id"], "comment", f"@{name} commented on your Reel", video_id)

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
        INSERT OR IGNORE INTO shares
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

    raw_video_id = str(video_id)[7:] if str(video_id).startswith("upload_") else str(video_id)
    owner = db.execute("SELECT user_id FROM videos WHERE CAST(id AS TEXT)=?", (raw_video_id,)).fetchone()
    if owner and owner["user_id"]:
        actor = db.execute("SELECT username FROM users WHERE id=?", (session["user_id"],)).fetchone()
        name = (actor["username"] or "Someone").split("@")[0]
        create_notification(db, owner["user_id"], session["user_id"], "share", f"@{name} shared your Reel", video_id)

    db.commit()

    db.close()

    return jsonify({
        "success": True,
        "count": count
    })


# =========================================================
# SAVED REELS / SEARCH / FRIEND ACTIVITY
# =========================================================
@app.route("/api/save/<video_id>", methods=["POST"])
def save_video(video_id):
    if not logged_in(): return jsonify({"success":False,"login_required":True}),401
    db=get_db(); me=session["user_id"]
    row=db.execute("SELECT id FROM saved_videos WHERE user_id=? AND video_id=?",(me,video_id)).fetchone()
    if row:
        db.execute("DELETE FROM saved_videos WHERE id=?",(row["id"],)); saved=False
    else:
        db.execute("INSERT OR IGNORE INTO saved_videos(user_id,video_id) VALUES(?,?)",(me,video_id)); saved=True
    db.commit(); db.close(); return jsonify({"success":True,"saved":saved})

@app.route("/api/saved-videos")
def saved_videos():
    if not logged_in(): return jsonify([]),401
    db=get_db(); me=session["user_id"]
    rows=db.execute("""
        SELECT s.video_id, v.id, v.title, v.url, v.creator, v.caption, v.tags, v.privacy, u.username, u.uid, u.photo
        FROM saved_videos s LEFT JOIN videos v ON (CAST(v.id AS TEXT)=s.video_id OR ('upload_'||v.id)=s.video_id)
        LEFT JOIN users u ON u.id=v.user_id WHERE s.user_id=? ORDER BY s.id DESC
    """,(me,)).fetchall(); db.close()
    return jsonify([dict(r) for r in rows if r["url"]])

@app.route("/api/search")
def search_all():
    if not logged_in(): return jsonify({"success":False}),401
    q=str(request.args.get("q","")).strip()[:80]
    if not q: return jsonify({"users":[],"videos":[]})
    db=get_db(); like="%"+q+"%"
    users=db.execute("SELECT username,uid,photo,bio FROM users WHERE username LIKE ? OR uid LIKE ? ORDER BY username LIMIT 30",(like,like)).fetchall()
    videos=db.execute("SELECT id,title,url,creator,caption,tags,privacy FROM videos WHERE privacy='public' AND (creator LIKE ? OR title LIKE ? OR caption LIKE ? OR tags LIKE ?) ORDER BY id DESC LIMIT 30",(like,like,like,like)).fetchall()
    db.close()
    return jsonify({"users":[dict(x) for x in users],"videos":[{**dict(x),"id":"upload_"+str(x["id"])} for x in videos]})

@app.route("/api/friend-comments")
def friend_comments():
    if not logged_in(): return jsonify([]),401
    db=get_db(); me=session["user_id"]
    rows=db.execute("""
      SELECT c.id,c.comment,c.created_at,c.video_id,
             cu.username commenter,cu.uid commenter_uid,cu.photo commenter_photo,
             v.title,v.url,v.creator,v.caption,
             vo.username owner_username,vo.uid owner_uid
      FROM comments c JOIN users cu ON cu.id=c.user_id
      LEFT JOIN videos v ON CAST(v.id AS TEXT)=CASE WHEN c.video_id LIKE 'upload_%' THEN substr(c.video_id,8) ELSE c.video_id END
      LEFT JOIN users vo ON vo.id=v.user_id
      WHERE c.user_id IN (
        SELECT CASE WHEN f.user1_id=? THEN f.user2_id ELSE f.user1_id END FROM friends f WHERE f.user1_id=? OR f.user2_id=?
      )
      ORDER BY c.id DESC LIMIT 100
    """,(me,me,me)).fetchall(); db.close(); return jsonify([dict(r) for r in rows])

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
            user_id
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
            request.form.get("caption", "").strip(),
            request.form.get("tags", "").strip(),
            request.form.get("privacy", "public").strip().lower() or "public",
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

    rows = db.execute(
        """
        SELECT
            id, title, url, creator, source, caption, tags, privacy, user_id
        FROM videos
        WHERE COALESCE(privacy, 'public')='public'
        ORDER BY id DESC
        """
    ).fetchall()

    db.close()

    return jsonify([

        {
            "id":
                "upload_"
                +
                str(
                    row["id"]
                ),

            "title":
                row["title"],

            "url":
                row["url"],

            "creator":
                row["creator"],

            "source": row["source"],
            "caption": row["caption"],
            "tags": row["tags"],
            "privacy": row["privacy"] or "public",
            "user_id": row["user_id"]

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
# MY PROFILE PAGE
# =========================================================

@app.route("/profile")
def my_profile():
    if not logged_in():
        return redirect(url_for("login"))

    db = get_db()
    user = db.execute(
        '''
        SELECT id, username, uid, gender, age, photo, bio,
               location, phone, privacy
        FROM users
        WHERE id=?
        ''',
        (session["user_id"],)
    ).fetchone()
    db.close()

    if not user:
        session.clear()
        return redirect(url_for("login"))

    return render_template("profile_view.html", user=dict(user))


# =========================================================
# SWITCH ACCOUNT
# =========================================================

@app.route("/switch-account")
def switch_account():
    clear_otp_session()
    session.clear()
    return redirect(url_for("login"))


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
# SOCIAL: FOLLOWERS / FOLLOWING
# =========================================================

def _current_user_id():
    return session.get("user_id")


def _are_mutual_followers(db, a, b):
    x = db.execute("SELECT 1 FROM follows WHERE follower_id=? AND following_id=?", (a,b)).fetchone()
    y = db.execute("SELECT 1 FROM follows WHERE follower_id=? AND following_id=?", (b,a)).fetchone()
    return bool(x and y)


@app.route("/api/follow/<uid>", methods=["POST"])
def follow_user(uid):
    if not logged_in(): return jsonify({"success":False,"login_required":True}),401
    db=get_db(); me=session["user_id"]
    target=db.execute("SELECT id,username FROM users WHERE uid=?",(uid,)).fetchone()
    if not target: db.close(); return jsonify({"success":False,"message":"User not found."}),404
    other=target["id"]
    if me==other: db.close(); return jsonify({"success":False,"message":"You cannot follow yourself."})
    blocked=db.execute("SELECT 1 FROM blocks WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)",(me,other,other,me)).fetchone()
    if blocked: db.close(); return jsonify({"success":False,"message":"Follow unavailable."})
    existing=db.execute("SELECT 1 FROM follows WHERE follower_id=? AND following_id=?",(me,other)).fetchone()
    if not existing:
        db.execute("INSERT INTO follows(follower_id,following_id) VALUES(?,?)",(me,other))
        actor=db.execute("SELECT username FROM users WHERE id=?",(me,)).fetchone()
        name=(actor["username"] or "Someone").split("@")[0]
        create_notification(db, other, me, "follow", f"@{name} started following you")
        db.commit()
    db.close(); return jsonify({"success":True,"following":True})


@app.route("/api/unfollow/<uid>", methods=["POST"])
def unfollow_user(uid):
    if not logged_in(): return jsonify({"success":False}),401
    db=get_db(); target=db.execute("SELECT id FROM users WHERE uid=?",(uid,)).fetchone()
    if target: db.execute("DELETE FROM follows WHERE follower_id=? AND following_id=?",(session["user_id"],target["id"])); db.commit()
    db.close(); return jsonify({"success":True,"following":False})


@app.route("/api/follow-status/<uid>")
def follow_status(uid):
    if not logged_in(): return jsonify({"success":False}),401
    db=get_db(); target=db.execute("SELECT id FROM users WHERE uid=?",(uid,)).fetchone()
    if not target: db.close(); return jsonify({"success":False}),404
    me=session["user_id"]; other=target["id"]
    following=bool(db.execute("SELECT 1 FROM follows WHERE follower_id=? AND following_id=?",(me,other)).fetchone())
    follower=bool(db.execute("SELECT 1 FROM follows WHERE follower_id=? AND following_id=?",(other,me)).fetchone())
    db.close(); return jsonify({"success":True,"following":following,"follows_you":follower,"mutual":following and follower})


@app.route("/api/followers")
def followers():
    if not logged_in(): return jsonify([]),401
    db=get_db(); rows=db.execute("SELECT u.username,u.uid,u.photo FROM follows f JOIN users u ON u.id=f.follower_id WHERE f.following_id=? ORDER BY f.id DESC",(session["user_id"],)).fetchall(); db.close(); return jsonify([dict(r) for r in rows])


@app.route("/api/following")
def following():
    if not logged_in(): return jsonify([]),401
    db=get_db(); rows=db.execute("SELECT u.username,u.uid,u.photo FROM follows f JOIN users u ON u.id=f.following_id WHERE f.follower_id=? ORDER BY f.id DESC",(session["user_id"],)).fetchall(); db.close(); return jsonify([dict(r) for r in rows])


@app.route("/api/profile/<uid>")
def public_profile(uid):
    if not logged_in(): return jsonify({"success":False}),401
    db=get_db()
    u=db.execute("SELECT id,username,uid,gender,age,photo,bio,location,privacy,last_seen,last_seen_privacy,membership,membership_until FROM users WHERE uid=?",(uid,)).fetchone()
    if not u: db.close(); return jsonify({"success":False,"message":"User not found."}),404
    me=session["user_id"]; other=u["id"]
    following=bool(db.execute("SELECT 1 FROM follows WHERE follower_id=? AND following_id=?",(me,other)).fetchone())
    follows_you=bool(db.execute("SELECT 1 FROM follows WHERE follower_id=? AND following_id=?",(other,me)).fetchone())
    is_friend=bool(db.execute("SELECT 1 FROM friends WHERE (user1_id=? AND user2_id=?) OR (user1_id=? AND user2_id=?)",(me,other,other,me)).fetchone())
    followers_count=db.execute("SELECT COUNT(*) c FROM follows WHERE following_id=?",(other,)).fetchone()["c"]
    following_count=db.execute("SELECT COUNT(*) c FROM follows WHERE follower_id=?",(other,)).fetchone()["c"]
    can_view_private=(me==other) or follows_you
    if can_view_private:
        video_rows=db.execute("SELECT id,title,url,creator,source,caption,tags,privacy FROM videos WHERE user_id=? ORDER BY id DESC",(other,)).fetchall()
    else:
        video_rows=db.execute("SELECT id,title,url,creator,source,caption,tags,privacy FROM videos WHERE user_id=? AND privacy!='private' ORDER BY id DESC",(other,)).fetchall()
    videos=[]
    for r in video_rows:
        item=dict(r)
        raw_id=str(r["id"])
        item["id"]="upload_"+raw_id
        item["likes_count"]=db.execute("SELECT COUNT(*) c FROM likes WHERE video_id IN (?,?)", (raw_id, "upload_"+raw_id)).fetchone()["c"]
        item["saved"]=bool(db.execute("SELECT 1 FROM saved_videos WHERE user_id=? AND video_id IN (?,?)", (me, raw_id, "upload_"+raw_id)).fetchone())
        videos.append(item)
    show_last=(me==other) or (u["last_seen_privacy"]=="public") or (u["last_seen_privacy"]=="private" and is_friend)
    data=dict(u); data.pop("id",None)
    if not show_last: data["last_seen"]=None
    data.update({"following":following,"follows_you":follows_you,"mutual":following and follows_you,"is_friend":is_friend,"followers_count":followers_count,"following_count":following_count,"videos":videos,"video_count":len(videos),"private_visible":can_view_private,"show_last_seen":show_last,"subscribed":bool(u["membership"]),"membership_until":u["membership_until"]})
    db.close(); return jsonify({"success":True,"user":data})


@app.route("/api/profile/<uid>/followers")
def profile_followers(uid):
    if not logged_in(): return jsonify([]),401
    db=get_db(); u=db.execute("SELECT id FROM users WHERE uid=?",(uid,)).fetchone()
    if not u: db.close(); return jsonify([]),404
    rows=db.execute("SELECT users.username,users.uid,users.photo,users.bio FROM follows JOIN users ON users.id=follows.follower_id WHERE follows.following_id=? ORDER BY follows.id DESC",(u["id"],)).fetchall(); db.close(); return jsonify([dict(r) for r in rows])

@app.route("/api/profile/<uid>/following")
def profile_following(uid):
    if not logged_in(): return jsonify([]),401
    db=get_db(); u=db.execute("SELECT id FROM users WHERE uid=?",(uid,)).fetchone()
    if not u: db.close(); return jsonify([]),404
    rows=db.execute("SELECT users.username,users.uid,users.photo,users.bio FROM follows JOIN users ON users.id=follows.following_id WHERE follows.follower_id=? ORDER BY follows.id DESC",(u["id"],)).fetchall(); db.close(); return jsonify([dict(r) for r in rows])

@app.route("/api/my-videos")
def my_videos():
    if not logged_in(): return jsonify([]),401
    db=get_db(); rows=db.execute("SELECT id,title,url,creator,source,caption,tags,privacy FROM videos WHERE user_id=? ORDER BY id DESC",(session["user_id"],)).fetchall(); db.close()
    return jsonify([{**dict(r),"id":"upload_"+str(r["id"])} for r in rows])


@app.route("/api/friend-videos")
def friend_videos():
    if not logged_in():
        return jsonify({"success": False, "videos": [], "message": "Please log in again."}), 401

    db = get_db()
    me = session["user_id"]
    try:
        rows = db.execute("""
            SELECT v.id, v.title, v.url, v.creator, v.source, v.caption, v.tags,
                   v.privacy, u.username, u.uid, u.photo
            FROM videos v
            INNER JOIN users u ON u.id = v.user_id
            WHERE v.privacy = 'public'
              AND EXISTS (
                  SELECT 1 FROM friends f
                  WHERE (f.user1_id = ? AND f.user2_id = u.id)
                     OR (f.user2_id = ? AND f.user1_id = u.id)
              )
            ORDER BY v.id DESC
        """, (me, me)).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            item["id"] = "upload_" + str(r["id"])
            item["creator"] = (r["username"] or "friend").split("@")[0]
            result.append(item)
        return jsonify({"success": True, "videos": result})
    except Exception as e:
        print("Friend reels error:", e)
        return jsonify({"success": False, "videos": [], "message": "Friends Reels are temporarily unavailable."}), 500
    finally:
        db.close()


# =========================================================
# DIAMONDS / MEMBERSHIP
# =========================================================
DIAMOND_PACKAGES = {10:11, 29:29, 48:60, 250:270, 621:640, 1000:1020}

@app.route("/api/wallet")
def wallet():
    if not logged_in(): return jsonify({"success":False}),401
    db=get_db(); u=db.execute("SELECT diamonds,membership,membership_until FROM users WHERE id=?",(session["user_id"],)).fetchone(); db.close()
    return jsonify({"success":True,"diamonds":u["diamonds"] or 0,"membership":bool(u["membership"]),"membership_until":u["membership_until"]})

@app.route("/api/diamond-order", methods=["POST"])
def diamond_order():
    if not logged_in(): return jsonify({"success":False}),401
    data=request.get_json(silent=True) or {}
    try: rupees=int(data.get("rupees",0))
    except: rupees=0
    if rupees not in DIAMOND_PACKAGES: return jsonify({"success":False,"message":"Invalid diamond package."}),400
    txn=str(data.get("txn_id","")).strip()[:100]
    db=get_db(); cur=db.execute("INSERT INTO diamond_orders(user_id,rupees,diamonds,txn_id) VALUES(?,?,?,?)",(session["user_id"],rupees,DIAMOND_PACKAGES[rupees],txn)); db.commit(); order_id=cur.lastrowid; db.close()
    return jsonify({"success":True,"order_id":order_id,"diamonds":DIAMOND_PACKAGES[rupees],"message":"Payment submitted for verification. Diamonds will be credited after payment is verified."})

@app.route("/api/payment-status")
def payment_status():
    if not logged_in(): return jsonify({"success":False,"message":"Login required."}),401
    txn=str(request.args.get("txn_id","")).strip()[:100]
    if not txn: return jsonify({"success":False,"message":"Enter a transaction ID."}),400
    db=get_db(); row=db.execute("SELECT id,rupees,diamonds,order_type,status,txn_id,created_at FROM diamond_orders WHERE user_id=? AND txn_id=? ORDER BY id DESC LIMIT 1",(session["user_id"],txn)).fetchone(); db.close()
    if not row: return jsonify({"success":False,"message":"No payment order found for this transaction ID."}),404
    return jsonify({"success":True,**dict(row)})


@app.route("/api/membership-order", methods=["POST"])
def membership_order():
    if not logged_in(): return jsonify({"success":False}),401
    data=request.get_json(silent=True) or {}; txn=str(data.get("txn_id","")).strip()[:100]
    db=get_db(); cur=db.execute("INSERT INTO diamond_orders(user_id,rupees,diamonds,order_type,txn_id) VALUES(?,?,?,?,?)",(session["user_id"],29,29,"membership",txn)); db.commit(); order_id=cur.lastrowid; db.close()
    return jsonify({"success":True,"order_id":order_id,"message":"Membership payment submitted for verification. Membership and 29 diamonds activate after verification."})


# =========================================================
# MESSAGES: ONLY MUTUAL FOLLOWERS
# =========================================================
@app.route("/api/message/<uid>", methods=["POST"])
def send_message(uid):
    if not logged_in(): return jsonify({"success":False,"login_required":True}),401
    data=request.get_json(silent=True) or {}; text=str(data.get("message","")).strip()
    if not text: return jsonify({"success":False,"message":"Message is empty."}),400
    db=get_db(); target=db.execute("SELECT id,username FROM users WHERE uid=?",(uid,)).fetchone()
    if not target: db.close(); return jsonify({"success":False,"message":"User not found."}),404
    me=session["user_id"]; other=target["id"]
    if not _are_mutual_followers(db,me,other): db.close(); return jsonify({"success":False,"message":"Both users must follow each other before messaging."}),403
    blocked=db.execute("SELECT 1 FROM blocks WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)",(me,other,other,me)).fetchone()
    if blocked: db.close(); return jsonify({"success":False,"message":"Messaging unavailable."}),403
    db.execute("INSERT INTO messages(sender_id,receiver_id,message) VALUES(?,?,?)",(me,other,text)); create_notification(db, other, me, "message", "@" + target["username"] + " sent you a message"); db.commit(); db.close(); return jsonify({"success":True})


@app.route("/api/messages/<uid>")
def get_messages(uid):
    if not logged_in(): return jsonify([]),401
    db=get_db(); target=db.execute("SELECT id FROM users WHERE uid=?",(uid,)).fetchone()
    if not target: db.close(); return jsonify([]),404
    me=session["user_id"]; other=target["id"]
    if not _are_mutual_followers(db,me,other): db.close(); return jsonify({"success":False,"message":"Messaging requires mutual following."}),403
    rows=db.execute("SELECT m.id,m.message,m.created_at,u.username FROM messages m JOIN users u ON u.id=m.sender_id WHERE (m.sender_id=? AND m.receiver_id=?) OR (m.sender_id=? AND m.receiver_id=?) ORDER BY m.id ASC",(me,other,other,me)).fetchall(); db.close(); return jsonify([dict(r) for r in rows])


@app.route("/api/chats")
def chats():
    if not logged_in(): return jsonify([]),401
    db=get_db(); me=session["user_id"]
    rows=db.execute("""SELECT u.username,u.uid,u.photo,MAX(m.id) last_id FROM messages m JOIN users u ON u.id=CASE WHEN m.sender_id=? THEN m.receiver_id ELSE m.sender_id END WHERE m.sender_id=? OR m.receiver_id=? GROUP BY u.id ORDER BY last_id DESC""",(me,me,me)).fetchall(); db.close(); return jsonify([dict(r) for r in rows])


# =========================================================
# GROUPS
# =========================================================
@app.route("/api/groups", methods=["GET","POST"])
def groups_api():
    if not logged_in(): return jsonify({"success":False}),401
    db=get_db(); me=session["user_id"]
    if request.method=="POST":
        data=request.get_json(silent=True) or {}; name=str(data.get("name","")).strip()[:80]
        if not name: db.close(); return jsonify({"success":False,"message":"Group name required."}),400
        cur=db.execute("INSERT INTO groups(name,owner_id) VALUES(?,?)",(name,me)); gid=cur.lastrowid; db.execute("INSERT INTO group_members(group_id,user_id) VALUES(?,?)",(gid,me)); db.commit(); db.close(); return jsonify({"success":True,"id":gid,"name":name})
    rows=db.execute("SELECT g.id,g.name,g.owner_id FROM groups g JOIN group_members gm ON gm.group_id=g.id WHERE gm.user_id=? ORDER BY g.id DESC",(me,)).fetchall(); db.close(); return jsonify([dict(r) for r in rows])


@app.route("/api/groups/<int:group_id>/members", methods=["POST"])
def add_group_member(group_id):
    if not logged_in(): return jsonify({"success":False}),401
    data=request.get_json(silent=True) or {}; uid=str(data.get("uid","")).strip(); db=get_db(); me=session["user_id"]
    g=db.execute("SELECT owner_id FROM groups WHERE id=?",(group_id,)).fetchone(); u=db.execute("SELECT id FROM users WHERE uid=?",(uid,)).fetchone()
    if not g or not u: db.close(); return jsonify({"success":False,"message":"Group or user not found."}),404
    if g["owner_id"]!=me: db.close(); return jsonify({"success":False,"message":"Only the group owner can add members."}),403
    db.execute("INSERT OR IGNORE INTO group_members(group_id,user_id) VALUES(?,?)",(group_id,u["id"])); db.commit(); db.close(); return jsonify({"success":True})


@app.route("/api/groups/<int:group_id>/messages", methods=["GET","POST"])
def group_messages_api(group_id):
    if not logged_in(): return jsonify({"success":False}),401
    db=get_db(); me=session["user_id"]
    member=db.execute("SELECT 1 FROM group_members WHERE group_id=? AND user_id=?",(group_id,me)).fetchone()
    if not member: db.close(); return jsonify({"success":False,"message":"You are not a group member."}),403
    if request.method=="POST":
        data=request.get_json(silent=True) or {}; text=str(data.get("message","")).strip()
        if not text: db.close(); return jsonify({"success":False,"message":"Message is empty."}),400
        db.execute("INSERT INTO group_messages(group_id,sender_id,message) VALUES(?,?,?)",(group_id,me,text)); db.commit(); db.close(); return jsonify({"success":True})
    rows=db.execute("SELECT gm.message,gm.created_at,u.username FROM group_messages gm JOIN users u ON u.id=gm.sender_id WHERE gm.group_id=? ORDER BY gm.id ASC",(group_id,)).fetchall(); db.close(); return jsonify([dict(r) for r in rows])

# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    import threading
    threading.Thread(target=warm_reels_cache, daemon=True).start()

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
