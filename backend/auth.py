import os, re, time, secrets, hashlib
from urllib.parse import urlencode
import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from database import get_db
from config import SECRET_KEY, is_production

router = APIRouter(prefix='/api/auth', tags=['auth'])
OTP_EXPIRY = 180
OTP_MAX_ATTEMPTS = 3
OTP_LOCK = 300
if not SECRET_KEY:
    SECRET_KEY = 'dev-only-change-me'
serializer = URLSafeTimedSerializer(SECRET_KEY, salt='ticktock-api')

class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

class LoginIn(RegisterIn):
    pass

class OTPIn(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=6, max_length=6)

class ResetIn(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8, max_length=128)


def clean_email(email: str) -> str:
    return email.strip().lower()


def valid_password(password: str) -> bool:
    return bool(re.search(r'[A-Za-z]', password) and re.search(r'\d', password))


def make_otp() -> str:
    return f'{secrets.randbelow(1_000_000):06d}'


def otp_hash(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()


def send_otp(email: str, otp: str) -> bool:
    # Prefer Resend when configured; otherwise SMTP.
    resend_key = os.getenv('RESEND_API_KEY', '').strip()
    from_email = os.getenv('EMAIL_FROM', 'onboarding@resend.dev').strip()
    if resend_key:
        try:
            r = requests.post('https://api.resend.com/emails', headers={'Authorization': f'Bearer {resend_key}', 'Content-Type': 'application/json'}, json={'from': from_email, 'to': [email], 'subject': 'Tick Tock verification code', 'html': f'<p>Your Tick Tock verification code is <b>{otp}</b>.</p><p>It expires in 3 minutes.</p>'}, timeout=15)
            return r.ok
        except requests.RequestException:
            return False
    host = os.getenv('SMTP_HOST', '').strip(); user = os.getenv('SMTP_USER', '').strip(); password = os.getenv('SMTP_PASSWORD', '').strip()
    if not (host and user and password):
        print(f'OTP for {email}: {otp} (configure email env vars for production)')
        return False
    import smtplib
    from email.message import EmailMessage
    try:
        port = int(os.getenv('SMTP_PORT', '587'))
        msg = EmailMessage(); msg['Subject']='Tick Tock verification code'; msg['From']=from_email or user; msg['To']=email
        msg.set_content(f'Your Tick Tock verification code is {otp}. It expires in 3 minutes.')
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls(); s.login(user, password); s.send_message(msg)
        return True
    except Exception:
        return False


def save_otp(user_id, email, purpose, otp):
    with get_db() as db:
        db.execute('DELETE FROM auth_otps WHERE email=? AND purpose=?', (email, purpose))
        db.execute('INSERT INTO auth_otps (user_id,email,purpose,otp_hash,expires_at,attempts,locked_until) VALUES (?,?,?,?,?,?,?)', (user_id,email,purpose,otp_hash(otp),time.time()+OTP_EXPIRY,0,0))


def verify_saved_otp(email, purpose, otp):
    with get_db() as db:
        row = db.execute('SELECT * FROM auth_otps WHERE email=? AND purpose=?', (email,purpose)).fetchone()
        if not row: raise HTTPException(400, 'OTP not found. Please request a new OTP.')
        now=time.time()
        if now < float(row['locked_until'] or 0): raise HTTPException(429, 'Too many wrong attempts. Try again later.')
        if now > float(row['expires_at']):
            db.execute('DELETE FROM auth_otps WHERE id=?',(row['id'],)); raise HTTPException(400,'OTP expired. Please request a new one.')
        if otp_hash(otp) != row['otp_hash']:
            attempts=int(row['attempts'] or 0)+1
            locked=now+OTP_LOCK if attempts>=OTP_MAX_ATTEMPTS else 0
            db.execute('UPDATE auth_otps SET attempts=?,locked_until=? WHERE id=?',(attempts,locked,row['id']))
            raise HTTPException(400, 'Wrong OTP.')
        db.execute('DELETE FROM auth_otps WHERE id=?',(row['id'],))
        return True


def token_for_user(user_id):
    return serializer.dumps({'user_id': int(user_id)})


def user_public(row):
    return {'id': row['id'], 'username': row['username'], 'uid': row['uid'], 'display_name': row['display_name'], 'profile_complete': bool(row['profile_complete']), 'email_verified': bool(row['email_verified'])}

@router.get('/status')
def status():
    return {'status':'ready','provider':'FastAPI','otp':'email'}

@router.post('/register')
def register(data: RegisterIn):
    email=clean_email(str(data.email))
    if not email.endswith('@gmail.com'): raise HTTPException(400,'Please use a Gmail address.')
    if not valid_password(data.password): raise HTTPException(400,'Password must contain letters and numbers.')
    with get_db() as db:
        if db.execute('SELECT id FROM users WHERE lower(username)=?',(email,)).fetchone(): raise HTTPException(409,'Gmail already registered. Please login.')
        uid='TT'+secrets.token_hex(6).upper(); friend_uid='FR'+secrets.token_hex(6).upper()
        cur=db.execute('INSERT INTO users (username,password,uid,friend_uid,profile_complete,email_verified) VALUES (?,?,?,?,0,0)',(email,generate_password_hash(data.password),uid,friend_uid))
        user_id=cur.lastrowid
    otp=make_otp(); save_otp(user_id,email,'register',otp)
    if not send_otp(email,otp): raise HTTPException(503,'Account created, but OTP email could not be sent. Configure email settings.')
    return {'message':'OTP sent','email':email}

@router.post('/verify-otp')
def verify_register(data: OTPIn):
    email=clean_email(str(data.email)); verify_saved_otp(email,'register',data.otp)
    with get_db() as db:
        db.execute('UPDATE users SET email_verified=1 WHERE lower(username)=?',(email,)); row=db.execute('SELECT * FROM users WHERE lower(username)=?',(email,)).fetchone()
    return {'message':'Email verified','access_token':token_for_user(row['id']),'token_type':'bearer','user':user_public(row)}

@router.post('/login')
def login(data: LoginIn):
    email=clean_email(str(data.email))
    with get_db() as db: user=db.execute('SELECT * FROM users WHERE lower(username)=?',(email,)).fetchone()
    if not user: raise HTTPException(404,'Account not found. Please register first.')
    if not check_password_hash(user['password'],data.password): raise HTTPException(401,'Wrong password.')
    otp=make_otp(); save_otp(user['id'],email,'login',otp)
    if not send_otp(email,otp): raise HTTPException(503,'OTP could not be sent. Configure email settings.')
    return {'message':'OTP sent','otp_required':True,'email':email}

@router.post('/verify-login-otp')
def verify_login(data: OTPIn):
    email=clean_email(str(data.email)); verify_saved_otp(email,'login',data.otp)
    with get_db() as db:
        db.execute('UPDATE users SET email_verified=1 WHERE lower(username)=?',(email,)); row=db.execute('SELECT * FROM users WHERE lower(username)=?',(email,)).fetchone()
    return {'message':'Login successful','access_token':token_for_user(row['id']),'token_type':'bearer','user':user_public(row)}

@router.post('/forgot-password')
def forgot(data: dict):
    email=clean_email(str(data.get('email','')))
    with get_db() as db: user=db.execute('SELECT id,username FROM users WHERE lower(username)=?',(email,)).fetchone()
    if not user: raise HTTPException(404,'Gmail is not registered on Tick Tock.')
    otp=make_otp(); save_otp(user['id'],email,'reset',otp)
    if not send_otp(email,otp): raise HTTPException(503,'Reset OTP could not be sent. Configure email settings.')
    return {'message':'Reset OTP sent','email':email}

@router.post('/reset-password')
def reset(data: ResetIn):
    email=clean_email(str(data.email)); verify_saved_otp(email,'reset',data.otp)
    if not valid_password(data.new_password): raise HTTPException(400,'Password must contain letters and numbers.')
    with get_db() as db:
        db.execute('UPDATE users SET password=? WHERE lower(username)=?',(generate_password_hash(data.new_password),email))
    return {'message':'Password reset successfully'}

@router.get('/google')
def google_login():
    cid=os.getenv('GOOGLE_CLIENT_ID','').strip(); redirect_uri=os.getenv('GOOGLE_REDIRECT_URI','').strip()
    if not cid or not redirect_uri: raise HTTPException(503,'Google Login is not configured. Add GOOGLE_CLIENT_ID and GOOGLE_REDIRECT_URI.')
    state=secrets.token_urlsafe(24)
    params=urlencode({'client_id':cid,'redirect_uri':redirect_uri,'response_type':'code','scope':'openid email profile','state':state,'access_type':'online','prompt':'select_account'})
    return RedirectResponse('https://accounts.google.com/o/oauth2/v2/auth?'+params)
