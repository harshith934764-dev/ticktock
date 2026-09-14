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

# Optional persistent directory for production hosting.
# When TICKTOCK_DATA_DIR is set on Render, the database and uploads
# live on the persistent disk instead of temporary service storage.
DATA_DIR = os.environ.get(
    "TICKTOCK_DATA_DIR",
    BASE_DIR
)

os.makedirs(DATA_DIR, exist_ok=True)

DB_FILE = os.path.join(
    DATA_DIR,
    "ticktock.db"
)

UPLOAD_FOLDER = os.path.join(
    DATA_DIR,
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

        uid = (
            "TTK-"
            +
            "".join(
                random.choices(
                    string.ascii_uppercase
                    +
                    string.digits,
                    k=10
                )
            )
        )

        found = db.execute(
            """
            SELECT id
            FROM users
            WHERE uid=?
            """,
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
        "profile_complete",
        "INTEGER DEFAULT 0"
    )

    users_without_uid = db.execute(
        """
        SELECT id
        FROM users
        WHERE uid IS NULL
        OR uid=''
        """
    ).fetchall()

    for user in users_without_uid:

        uid = create_uid(db)

        db.execute(
            """
            UPDATE users
            SET uid=?
            WHERE id=?
            """,
            (
                uid,
                user["id"]
            )
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


    db.execute(
        """
        CREATE TABLE IF NOT EXISTS follows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            follower_id INTEGER NOT NULL,
            following_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(follower_id, following_id)
        )
        """
    )

    # These migrations only ADD missing columns. Existing users,
    # password hashes, videos, likes, comments and friendships stay intact.
    add_column_if_missing(db, "videos", "caption", "TEXT")
    add_column_if_missing(db, "videos", "tags", "TEXT")
    add_column_if_missing(db, "videos", "privacy", "TEXT DEFAULT 'public'")
    add_column_if_missing(db, "videos", "uploader_id", "INTEGER")
    add_column_if_missing(db, "videos", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

    db.execute(
        """
        UPDATE videos
        SET uploader_id = (
            SELECT users.id
            FROM users
            WHERE users.username = videos.creator
        )
        WHERE uploader_id IS NULL
        """
    )

    db.execute(
        """
        UPDATE videos
        SET privacy='public'
        WHERE privacy IS NULL OR privacy=''
        """
    )

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
        uid=user["uid"]
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

    db.execute(
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

    db.commit()

    db.close()

    return redirect(
        url_for("login")
    )


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "GET":

        return render_template(
            "login.html"
        )

    email = request.form.get(
        "username",
        ""
    ).strip().lower()

    password = request.form.get(
        "password",
        ""
    )

    db = get_db()

    user = db.execute(
        """
        SELECT *
        FROM users
        WHERE username=?
        """,
        (email,)
    ).fetchone()

    db.close()

    if not user:

        return render_template(
            "login.html",
            error=(
                "Account not found ❌ "
                "Please register first."
            ),
            register_required=True,
            entered_email=email
        )

    if not check_password_hash(
        user["password"],
        password
    ):

        return render_template(
            "login.html",
            error="Wrong password ❌",
            entered_email=email
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

    session["otp_user_id"] = (
        user["id"]
    )

    session["otp_email"] = email

    sent = send_otp_email(
        email,
        otp
    )

    if not sent:

        clear_otp_session()

        return render_template(
            "login.html",
            error=(
                "OTP could not be sent. "
                "Email service is not "
                "configured yet."
            ),
            entered_email=email
        )

    return render_template(
        "login.html",
        otp_required=True,
        entered_email=email,
        otp_message=(
            "OTP sent to your Gmail 📩"
        )
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

    session["user_id"] = (
        user["id"]
    )

    session["username"] = (
        user["username"]
    )

    session["uid"] = (
        user["uid"]
    )

    if not user["profile_complete"]:

        return redirect(
            url_for(
                "profile_setup"
            )
        )

    return redirect(
        url_for("home")
    )


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

        return render_template(
            "profile.html",
            uid=session.get("uid")
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

    try:

        age = int(age_text)

    except ValueError:

        return render_template(
            "profile.html",
            uid=session.get("uid"),
            error=(
                "Enter a valid age."
            )
        )

    if age < 16 or age > 100:

        return render_template(
            "profile.html",
            uid=session.get("uid"),
            error=(
                "Age must be between "
                "16 and 100."
            )
        )

    photo = request.files.get(
        "photo"
    )

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
                error=(
                    "Use JPG, PNG or WEBP."
                )
            )

        photo_filename = (
            "profile_"
            +
            str(
                session["user_id"]
            )
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
                profile_complete=1
            WHERE id=?
            """,
            (
                gender,
                age,
                photo_filename,
                bio,
                location,
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
                profile_complete=1
            WHERE id=?
            """,
            (
                gender,
                age,
                bio,
                location,
                session["user_id"]
            )
        )

    db.commit()

    db.close()

    return redirect(
        url_for("home")
    )
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
            gender,
            age,
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
            gender,
            age,
            photo,
            bio,
            location
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
        """,
        (me, me)
    ).fetchall()

    db.close()

    return jsonify([dict(row) for row in rows])


@app.route("/api/follow/<uid>", methods=["POST"])
def follow_user(uid):
    if not logged_in():
        return jsonify({
            "success": False,
            "login_required": True
        }), 401

    db = get_db()

    target = db.execute(
        "SELECT id FROM users WHERE uid=?",
        (uid,)
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
            INSERT OR IGNORE INTO follows
            (follower_id, following_id)
            VALUES (?, ?)
            """,
            (me, target_id)
        )
        following = True

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
        SELECT users.id, users.username, users.uid,
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
        SELECT users.id, users.username, users.uid,
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


def get_pixabay_videos():

    global VIDEO_CACHE

    if VIDEO_CACHE:

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
                        50,

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

    VIDEO_CACHE = list(
        unique.values()
    )

    random.shuffle(
        VIDEO_CACHE
    )

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

    global VIDEO_CACHE

    VIDEO_CACHE = []

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

    db.commit()

    db.close()

    return jsonify({
        "success": True,
        "count": count
    })


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
            ) AS creator_followers
        FROM videos
        LEFT JOIN users
            ON users.id=videos.uploader_id
        WHERE videos.privacy='public'
           OR videos.privacy IS NULL
        ORDER BY videos.id DESC
        """
    ).fetchall()

    db.close()

    # Work out which creators the current user already follows.
    following_ids = set()
    current_user_id = session.get("user_id")
    if current_user_id:
        follow_db = get_db()
        following_ids = {
            row["following_id"]
            for row in follow_db.execute(
                "SELECT following_id FROM follows WHERE follower_id=?",
                (current_user_id,)
            ).fetchall()
        }
        follow_db.close()

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
            "is_following": bool(
                row["creator_uid"] and
                row["creator_uid"] in following_ids
            ),
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