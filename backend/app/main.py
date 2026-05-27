
from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import sqlite3, json, os, secrets, hashlib, hmac, base64, time, smtplib, threading
from .data_seed import COURSES, PRODUCTS, TOOLS, VIDEOS, ESCALATION_PROTOCOLS, AUTONOMY_MATRIX
from .seed_upload_pack import seed_upload_pack
try:
    import stripe
except Exception:
    stripe = None

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, '..'))
DB_PATH = os.getenv('DATABASE_FILE', os.path.join(ROOT_DIR, 'data', 'finnish_paradigm.sqlite'))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
FRONTEND_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', 'frontend'))
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

APP_NAME = os.getenv('APP_NAME', 'The Finnish Paradigm')
JWT_SECRET = os.getenv('JWT_SECRET', 'CHANGE_ME_BEFORE_LIVE_' + secrets.token_hex(16))
TOKEN_TTL_MINUTES = int(os.getenv('TOKEN_TTL_MINUTES', '480'))
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'admin@finnishparadigm.com')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'ChangeMeNow!123')
ALLOWED_ORIGINS = [o.strip() for o in os.getenv('ALLOWED_ORIGINS', 'http://localhost:8000,http://127.0.0.1:8000').split(',') if o.strip()]
STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY', '')
STRIPE_PRICE_TEACHER = os.getenv('STRIPE_PRICE_TEACHER', 'price_teacher_certificate')
STRIPE_PRICE_SCHOOL = os.getenv('STRIPE_PRICE_SCHOOL', 'price_school_license')
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', 'http://localhost:8000')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', '')
STRIPE_CURRENCY = os.getenv('STRIPE_CURRENCY', 'usd').lower()
STRIPE_TAX_AUTOMATIC = os.getenv('STRIPE_TAX_AUTOMATIC', '0') == '1'
STRIPE_ALLOW_PROMOTION_CODES = os.getenv('STRIPE_ALLOW_PROMOTION_CODES', '1') == '1'
STRIPE_BILLING_PORTAL_RETURN_URL = os.getenv('STRIPE_BILLING_PORTAL_RETURN_URL', PUBLIC_BASE_URL + '/dashboard.html')
STRIPE_PRICE_MAP = {k.replace('STRIPE_PRICE_', '').lower().replace('_','-'): v for k, v in os.environ.items() if k.startswith('STRIPE_PRICE_') and v}
SMTP_HOST = os.getenv('SMTP_HOST', '')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USERNAME = os.getenv('SMTP_USERNAME', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
SMTP_FROM = os.getenv('SMTP_FROM', ADMIN_EMAIL)
if stripe and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

RATE_LIMIT_WINDOW = int(os.getenv('RATE_LIMIT_WINDOW', '300'))
RATE_LIMIT_MAX_AUTH = int(os.getenv('RATE_LIMIT_MAX_AUTH', '15'))
RATE_LIMIT_MAX_BOOKING = int(os.getenv('RATE_LIMIT_MAX_BOOKING', '10'))

class RateLimiter:
    def __init__(self):
        self._attempts: Dict[str, list] = defaultdict(list)
        self._lock = threading.Lock()

    def check(self, key: str, window: int, max_attempts: int):
        now = time.time()
        with self._lock:
            self._attempts[key] = [t for t in self._attempts[key] if t > now - window]
            if len(self._attempts[key]) >= max_attempts:
                raise HTTPException(429, 'Too many requests. Please try again later.')
            self._attempts[key].append(now)

rate_limiter = RateLimiter()

def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get('x-forwarded-for')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.client.host if request.client else '0.0.0.0'

DB_SCHEMA_VERSION = 3

app = FastAPI(title=f'{APP_NAME} API', version='2.0.0', docs_url='/api/docs', redoc_url='/api/redoc')
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_credentials=True, allow_methods=['GET','POST','PUT','PATCH','DELETE','OPTIONS'], allow_headers=['Authorization','Content-Type'])

@app.middleware('http')
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Cache-Control'] = 'no-store' if '/api/' in request.url.path else 'public, max-age=3600'
    return response

app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')

# --------------------------- Models ---------------------------
class LoginIn(BaseModel):
    email: EmailStr
    password: str

class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    organisation: Optional[str] = ''
    role: Optional[str] = 'learner'

class BookingIn(BaseModel):
    name: str
    email: EmailStr
    organisation: Optional[str] = ''
    audience: str
    preferred_date: str
    message: Optional[str] = ''

class EnrollmentIn(BaseModel):
    course_id: str

class AssessmentStart(BaseModel):
    learner_name: str
    course_id: str

class AnswerIn(BaseModel):
    session_id: int
    item_id: int
    selected: str

class ItemIn(BaseModel):
    course_id: str
    difficulty: int = Field(ge=1, le=4)
    skill: str
    question: str
    options: List[str]
    correct: str
    explanation: str

class ProgressIn(BaseModel):
    course_id: str
    lesson_id: str
    completed: bool = True

class CheckoutIn(BaseModel):
    product_id: str
    customer_email: EmailStr
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None
    quantity: int = Field(default=1, ge=1, le=100)
    mode: Optional[str] = Field(default=None, description='payment or subscription. If omitted, product default is used.')

class BillingPortalIn(BaseModel):
    customer_email: EmailStr
    return_url: Optional[str] = None

class RefundIn(BaseModel):
    order_id: int
    amount: Optional[int] = Field(default=None, ge=1, description='Optional partial refund amount in cents')
    reason: Optional[str] = Field(default='requested_by_customer')

class InterventionCaseIn(BaseModel):
    student_code: str
    class_group: str
    risk_level: str
    concern: str
    evidence: str
    tier: int = Field(ge=1, le=3)
    assigned_to: Optional[str] = ''

# --------------------------- Security ---------------------------
def hash_password(password: str, salt: Optional[str]=None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 120000)
    return f'pbkdf2_sha256${salt}${base64.b64encode(digest).decode()}'

def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split('$', 2)
        return hmac.compare_digest(hash_password(password, salt), stored)
    except Exception:
        return False

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

def sign_token(payload: Dict[str, Any]) -> str:
    payload = dict(payload)
    payload['exp'] = int(time.time()) + TOKEN_TTL_MINUTES * 60
    body = b64url(json.dumps(payload, separators=(',', ':')).encode())
    sig = b64url(hmac.new(JWT_SECRET.encode(), body.encode(), hashlib.sha256).digest())
    return f'{body}.{sig}'

def read_token(token: str) -> Dict[str, Any]:
    try:
        body, sig = token.split('.', 1)
        expected = b64url(hmac.new(JWT_SECRET.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected): raise ValueError('bad signature')
        payload = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
        if payload.get('exp', 0) < time.time(): raise ValueError('expired')
        return payload
    except Exception:
        raise HTTPException(401, 'Invalid or expired token')

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn

def current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.lower().startswith('bearer '):
        raise HTTPException(401, 'Bearer token required')
    payload = read_token(authorization.split(' ', 1)[1])
    conn = db(); user = conn.execute('SELECT id,name,email,role,organisation,active FROM users WHERE id=?', (payload['sub'],)).fetchone(); conn.close()
    if not user or not user['active']: raise HTTPException(401, 'User not found or inactive')
    return dict(user)

def require_admin(user=Depends(current_user)):
    if user['role'] not in ('admin', 'manager'):
        raise HTTPException(403, 'Admin or manager role required')
    return user

# --------------------------- Database ---------------------------
def init_db():
    conn = db(); cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'learner', organisation TEXT DEFAULT '', active INTEGER DEFAULT 1, created_at TEXT NOT NULL)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS bookings(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, organisation TEXT, audience TEXT, preferred_date TEXT, message TEXT, status TEXT DEFAULT 'new', created_at TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS enrollments(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, email TEXT, course_id TEXT, status TEXT DEFAULT 'active', created_at TEXT, UNIQUE(user_id, course_id), FOREIGN KEY(user_id) REFERENCES users(id))''')
    cur.execute('''CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY AUTOINCREMENT, course_id TEXT, difficulty INTEGER, skill TEXT, question TEXT, options TEXT, correct TEXT, explanation TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS assessment_sessions(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, learner_name TEXT, course_id TEXT, ability REAL, started_at TEXT, finished INTEGER DEFAULT 0, FOREIGN KEY(user_id) REFERENCES users(id))''')
    cur.execute('''CREATE TABLE IF NOT EXISTS responses(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, item_id INTEGER, selected TEXT, correct INTEGER, created_at TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS progress(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, course_id TEXT, lesson_id TEXT, completed INTEGER DEFAULT 1, updated_at TEXT, UNIQUE(user_id, course_id, lesson_id))''')
    cur.execute('''CREATE TABLE IF NOT EXISTS intervention_cases(id INTEGER PRIMARY KEY AUTOINCREMENT, student_code TEXT, class_group TEXT, risk_level TEXT, concern TEXT, evidence TEXT, tier INTEGER, status TEXT DEFAULT 'open', assigned_to TEXT, created_at TEXT, updated_at TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, product_id TEXT, customer_email TEXT, amount INTEGER, currency TEXT, status TEXT, checkout_url TEXT, provider_ref TEXT, created_at TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY AUTOINCREMENT, customer_email TEXT, product_id TEXT, stripe_customer_id TEXT, stripe_subscription_id TEXT UNIQUE, status TEXT, current_period_end TEXT, created_at TEXT, updated_at TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS payment_events(id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE, event_type TEXT, provider_ref TEXT, payload TEXT, created_at TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS lms_courses(id INTEGER PRIMARY KEY AUTOINCREMENT, course_id TEXT UNIQUE NOT NULL, slug TEXT UNIQUE NOT NULL, title TEXT NOT NULL, category TEXT, level TEXT, duration TEXT, cpd_hours REAL, audience TEXT, aim TEXT, module_count INTEGER DEFAULT 0, published INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS lms_modules(id INTEGER PRIMARY KEY AUTOINCREMENT, module_id TEXT UNIQUE NOT NULL, course_id TEXT NOT NULL, title TEXT NOT NULL, scenario_setting TEXT, scenario_problem TEXT, practice_steps TEXT, reflective_checklist TEXT, video_script TEXT, sort_order INTEGER DEFAULT 0, published INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS module_videos(id INTEGER PRIMARY KEY AUTOINCREMENT, module_id TEXT UNIQUE NOT NULL, video_provider TEXT, video_url TEXT, video_embed_url TEXT, video_thumbnail_url TEXT, video_duration_seconds INTEGER, transcript TEXT, captions_url TEXT, video_status TEXT DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS lms_assessment_items(id INTEGER PRIMARY KEY AUTOINCREMENT, question_id TEXT UNIQUE NOT NULL, course_id TEXT NOT NULL, module_id TEXT, question TEXT NOT NULL, question_type TEXT DEFAULT 'short_answer_or_mcq', answer_focus TEXT, published INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS learner_progress(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, course_id TEXT NOT NULL, module_id TEXT, video_complete INTEGER DEFAULT 0, assessment_complete INTEGER DEFAULT 0, artifact_uploaded INTEGER DEFAULT 0, reflection_submitted INTEGER DEFAULT 0, module_complete INTEGER DEFAULT 0, completed_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id, course_id, module_id))''')
    cur.execute('''CREATE TABLE IF NOT EXISTS artifact_uploads(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, course_id TEXT NOT NULL, module_id TEXT NOT NULL, file_url TEXT, file_name TEXT, reflection_text TEXT, status TEXT DEFAULT 'submitted', reviewed_by INTEGER, reviewed_at TEXT, feedback TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS certificates(id INTEGER PRIMARY KEY AUTOINCREMENT, certificate_id TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL, course_id TEXT NOT NULL, learner_name TEXT NOT NULL, course_title TEXT NOT NULL, cpd_hours REAL, issued_at TEXT DEFAULT CURRENT_TIMESTAMP, certificate_url TEXT, verification_url TEXT, revoked INTEGER DEFAULT 0)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS course_products(id INTEGER PRIMARY KEY AUTOINCREMENT, course_id TEXT NOT NULL, product_id TEXT UNIQUE NOT NULL, stripe_price_id TEXT, price_amount REAL, currency TEXT DEFAULT 'gbp', payment_type TEXT DEFAULT 'one_time', active INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_lms_modules_course ON lms_modules(course_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_lms_assess_course ON lms_assessment_items(course_id, module_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_learner_prog_user ON learner_progress(user_id, course_id)')
    for col, spec in {
        'payment_provider':'TEXT DEFAULT \'stripe\'', 'stripe_customer_id':'TEXT DEFAULT \'\'', 'stripe_payment_intent':'TEXT DEFAULT \'\'', 'mode':'TEXT DEFAULT \'payment\'', 'paid_at':'TEXT DEFAULT \'\'', 'refunded_at':'TEXT DEFAULT \'\'', 'refunded_amount':'INTEGER DEFAULT 0', 'failure_reason':'TEXT DEFAULT \'\'', 'metadata':'TEXT DEFAULT \'{}\''
    }.items():
        try: cur.execute(f'ALTER TABLE orders ADD COLUMN {col} {spec}')
        except sqlite3.OperationalError: pass
    cur.execute('SELECT id FROM users WHERE email=?', (ADMIN_EMAIL,))
    if not cur.fetchone():
        cur.execute('INSERT INTO users(name,email,password_hash,role,organisation,created_at) VALUES(?,?,?,?,?,?)', ('Platform Admin', ADMIN_EMAIL, hash_password(ADMIN_PASSWORD), 'admin', 'Finnish Paradigm', datetime.now(timezone.utc).isoformat()))
    cur.execute('SELECT COUNT(*) AS c FROM items')
    if cur.fetchone()['c'] == 0:
        seed_items = [
            ('fcfp',1,'purpose','Which action is inside the teacher\'s sphere of control?', ['Changing ministry law','Giving clearer instructions','Changing national exams','Changing school ownership'], 'Giving clearer instructions','Teachers can directly control tone, instructions, scaffolds and classroom routines.'),
            ('fcfp',2,'45-15','In the 45-15 flow, what should the teacher use the 15-minute window for?', ['Email and marking','Observation and micro-intervention','Staff meetings','Punishment'], 'Observation and micro-intervention','The restorative window protects student attention and gives the teacher time to notice needs.'),
            ('fcfp',3,'ivf','A student shows a Red IVF marker three times in a week. What is the next step?', ['Ignore it','Open Tier 2 support','Remove the student permanently','Wait until final exam'], 'Open Tier 2 support','Repeated Red markers trigger targeted support, not blame.'),
            ('asti',2,'tiering','Tier 2 support is best described as:', ['Whole-class universal teaching','Targeted short-term intervention','Full exclusion','A ministry inspection'], 'Targeted short-term intervention','Tier 2 gives focused support when repeated difficulty is detected.'),
            ('asti',3,'retired-teacher','What is the senior asset role?', ['Take over the class','Co-teach the whole lesson','Provide targeted support without split authority','Replace the teacher'], 'Provide targeted support without split authority','Retired teachers act as intervention specialists while the main teacher keeps classroom command.'),
            ('seld',3,'leadership','What does a leadership dashboard track?', ['Only teacher attendance','Student risk, intervention cycles and progress','Only cafeteria sales','Only test rank'], 'Student risk, intervention cycles and progress','A dashboard should show who needs support and whether interventions are working.'),
            ('seld',4,'policy','Professional escalation should begin with:', ['Anger and public accusations','Evidence and written proposals','Ignoring leadership','Refusing all duties'], 'Evidence and written proposals','Safe advocacy is evidence-based, lawful and focused on student benefit.'),
            ('fcfp',2,'differentiation','Differentiation the Finnish Paradigm way means:', ['Lowering goals for weak students','Same goal with different support','Only teaching top students','Using no scaffolds'], 'Same goal with different support','The objective remains high; support is increased.'),
            ('asti',4,'tier3','Tier 3 should be activated when:', ['A student asks one question','Tier 2 gives no benchmark improvement over a review cycle','A teacher wants less work','A parent asks for grades only'], 'Tier 2 gives no benchmark improvement over a review cycle','Tier 3 is intensive and evidence-based.'),
            ('seld',2,'governance','A safe ministry petition should be:', ['Evidence-based and lawful','Anonymous insults','Public accusations without data','A refusal to teach'], 'Evidence-based and lawful','Escalation must be professional and student-focused.')
        ]
        for row in seed_items:
            cur.execute('INSERT INTO items(course_id,difficulty,skill,question,options,correct,explanation) VALUES(?,?,?,?,?,?,?)', (row[0],row[1],row[2],row[3],json.dumps(row[4]),row[5],row[6]))
    cur.execute('INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES(?,?)', (DB_SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()))
    conn.commit(); conn.close()

init_db()
try:
    seed_upload_pack(DB_PATH)
except Exception:
    pass

# --------------------------- Public API ---------------------------
@app.get('/api/health')
def health():
    try:
        conn = db(); conn.execute('SELECT 1'); conn.close()
        db_ok = True
    except Exception:
        db_ok = False
    return {'status':'ok' if db_ok else 'degraded','service':f'{APP_NAME} API','version':'2.0.0','database':'connected' if db_ok else 'error'}

@app.post('/api/admin/backup')
def create_backup(user=Depends(require_admin)):
    import shutil
    backup_dir = os.path.join(os.path.dirname(DB_PATH), 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(backup_dir, f'fp_backup_{timestamp}.sqlite')
    shutil.copy2(DB_PATH, backup_path)
    backups = sorted([f for f in os.listdir(backup_dir) if f.endswith('.sqlite')])
    while len(backups) > 10:
        os.remove(os.path.join(backup_dir, backups.pop(0)))
    return {'status':'backed_up','file':os.path.basename(backup_path),'total_backups':len(backups)}

@app.get('/api/admin/db-info')
def db_info(user=Depends(require_admin)):
    conn = db(); cur = conn.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
    counts = {t: cur.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0] for t in tables if t != 'schema_version'}
    version = cur.execute('SELECT MAX(version) FROM schema_version').fetchone()
    db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    conn.close()
    return {'schema_version': version[0] if version else 0, 'tables': counts, 'database_size_bytes': db_size, 'database_file': DB_PATH}

@app.get('/api/courses')
def courses(): return COURSES

@app.get('/api/courses/{course_id}')
def course(course_id: str):
    for c in COURSES:
        if c['id'] == course_id: return c
    raise HTTPException(404, 'Course not found')

@app.get('/api/products')
def products(): return PRODUCTS

@app.get('/api/tools')
def tools(): return TOOLS

@app.get('/api/videos')
def videos(): return VIDEOS

@app.get('/api/protocols')
def protocols(): return {'escalation': ESCALATION_PROTOCOLS, 'autonomy_matrix': AUTONOMY_MATRIX}

@app.post('/api/auth/register')
def register(payload: RegisterIn, request: Request):
    rate_limiter.check(f'register:{get_client_ip(request)}', RATE_LIMIT_WINDOW, RATE_LIMIT_MAX_AUTH)
    conn = db(); cur = conn.cursor()
    role = payload.role if payload.role in ('learner','teacher') else 'learner'
    try:
        cur.execute('INSERT INTO users(name,email,password_hash,role,organisation,created_at) VALUES(?,?,?,?,?,?)', (payload.name, payload.email.lower(), hash_password(payload.password), role, payload.organisation or '', datetime.now(timezone.utc).isoformat()))
        conn.commit(); uid = cur.lastrowid
    except sqlite3.IntegrityError:
        conn.close(); raise HTTPException(409, 'Email already registered')
    user = {'sub': uid, 'email': payload.email.lower(), 'role': role}
    token = sign_token(user)
    conn.close(); return {'access_token': token, 'token_type':'bearer','user': {'id':uid,'name':payload.name,'email':payload.email.lower(),'role':role}}

@app.post('/api/auth/login')
def login(payload: LoginIn, request: Request):
    rate_limiter.check(f'login:{get_client_ip(request)}', RATE_LIMIT_WINDOW, RATE_LIMIT_MAX_AUTH)
    conn = db(); user = conn.execute('SELECT * FROM users WHERE email=?', (payload.email.lower(),)).fetchone(); conn.close()
    if not user or not verify_password(payload.password, user['password_hash']):
        raise HTTPException(401, 'Incorrect email or password')
    if not user['active']: raise HTTPException(403, 'Account disabled')
    token = sign_token({'sub': user['id'], 'email': user['email'], 'role': user['role']})
    return {'access_token': token, 'token_type':'bearer','user': {'id':user['id'],'name':user['name'],'email':user['email'],'role':user['role'],'organisation':user['organisation']}}

@app.get('/api/auth/me')
def me(user=Depends(current_user)): return user

@app.post('/api/bookings')
def create_booking(payload: BookingIn, request: Request):
    rate_limiter.check(f'booking:{get_client_ip(request)}', RATE_LIMIT_WINDOW, RATE_LIMIT_MAX_BOOKING)
    conn=db(); cur=conn.cursor()
    cur.execute('INSERT INTO bookings(name,email,organisation,audience,preferred_date,message,status,created_at) VALUES(?,?,?,?,?,?,?,?)',(payload.name,payload.email,payload.organisation,payload.audience,payload.preferred_date,payload.message,'new',datetime.now(timezone.utc).isoformat()))
    conn.commit(); ident=cur.lastrowid; conn.close()
    send_email(payload.email, 'Finnish Paradigm consultation request received', f'Thank you {payload.name}. Your consultation request #{ident} has been received. We will respond with confirmation details.'); return {'id':ident,'status':'booked','message':'Consultation request saved. Email confirmation sent if SMTP is configured.'}

@app.post('/api/enrollments')
def enroll(payload: EnrollmentIn, user=Depends(current_user)):
    if not any(c['id']==payload.course_id for c in COURSES): raise HTTPException(404, 'Course not found')
    conn=db(); cur=conn.cursor()
    try:
        cur.execute('INSERT OR IGNORE INTO enrollments(user_id,name,email,course_id,status,created_at) VALUES(?,?,?,?,?,?)',(user['id'],user['name'],user['email'],payload.course_id,'active',datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally: conn.close()
    return {'status':'enrolled','course_id':payload.course_id}

@app.get('/api/my/enrollments')
def my_enrollments(user=Depends(current_user)):
    conn=db(); rows=[dict(r) for r in conn.execute('SELECT * FROM enrollments WHERE user_id=? ORDER BY id DESC',(user['id'],))]; conn.close(); return rows

@app.post('/api/my/progress')
def mark_progress(payload: ProgressIn, user=Depends(current_user)):
    conn=db(); cur=conn.cursor()
    cur.execute('INSERT INTO progress(user_id,course_id,lesson_id,completed,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id,course_id,lesson_id) DO UPDATE SET completed=excluded.completed, updated_at=excluded.updated_at', (user['id'],payload.course_id,payload.lesson_id,int(payload.completed),datetime.now(timezone.utc).isoformat()))
    conn.commit(); conn.close(); return {'status':'saved'}

@app.get('/api/my/progress')
def my_progress(user=Depends(current_user)):
    conn=db(); rows=[dict(r) for r in conn.execute('SELECT * FROM progress WHERE user_id=?',(user['id'],))]; conn.close(); return rows

# --------------------------- Assessments ---------------------------
@app.get('/api/item-bank')
def item_bank(course_id: Optional[str] = None, user=Depends(current_user)):
    conn=db()
    if course_id: rows=conn.execute('SELECT * FROM items WHERE course_id=? ORDER BY difficulty',(course_id,)).fetchall()
    else: rows=conn.execute('SELECT * FROM items ORDER BY course_id,difficulty').fetchall()
    conn.close()
    if user['role'] in ('admin', 'manager'):
        return [{**dict(r),'options':json.loads(r['options'])} for r in rows]
    return [{k:v for k,v in {**dict(r),'options':json.loads(r['options'])}.items() if k != 'correct'} for r in rows]

@app.post('/api/assessment/start')
def start_assessment(payload: AssessmentStart, user=Depends(current_user)):
    conn=db(); cur=conn.cursor()
    cur.execute('INSERT INTO assessment_sessions(user_id,learner_name,course_id,ability,started_at,finished) VALUES(?,?,?,?,?,0)',(user['id'],payload.learner_name,payload.course_id,2.0,datetime.now(timezone.utc).isoformat()))
    conn.commit(); sid=cur.lastrowid; conn.close(); return {'session_id':sid, 'next_item': get_next_item(sid)}

def get_next_item(session_id:int):
    conn=db(); cur=conn.cursor(); sess=cur.execute('SELECT * FROM assessment_sessions WHERE id=?',(session_id,)).fetchone()
    if not sess: conn.close(); raise HTTPException(404,'Session not found')
    answered=[r[0] for r in cur.execute('SELECT item_id FROM responses WHERE session_id=?',(session_id,)).fetchall()]
    ability=float(sess['ability']); target=max(1,min(4,round(ability)))
    query='SELECT * FROM items WHERE course_id=?'; params=[sess['course_id']]
    if answered:
        query += ' AND id NOT IN (%s)' % ','.join(['?']*len(answered)); params += answered
    query += ' ORDER BY ABS(difficulty-?), difficulty LIMIT 1'; params.append(target)
    item=cur.execute(query,params).fetchone(); conn.close()
    if not item: return None
    d=dict(item); d['options']=json.loads(d['options']); d.pop('correct',None); return d

@app.get('/api/assessment/{session_id}/next')
def next_item(session_id:int, user=Depends(current_user)):
    conn=db(); sess=conn.execute('SELECT user_id FROM assessment_sessions WHERE id=?',(session_id,)).fetchone(); conn.close()
    if not sess: raise HTTPException(404, 'Session not found')
    if sess['user_id'] != user['id'] and user['role'] not in ('admin','manager'): raise HTTPException(403, 'Not your session')
    return get_next_item(session_id)

@app.post('/api/assessment/answer')
def answer(payload: AnswerIn, user=Depends(current_user)):
    conn=db(); cur=conn.cursor(); item=cur.execute('SELECT * FROM items WHERE id=?',(payload.item_id,)).fetchone(); sess=cur.execute('SELECT * FROM assessment_sessions WHERE id=?',(payload.session_id,)).fetchone()
    if not item or not sess: conn.close(); raise HTTPException(404,'Item or session not found')
    if sess['user_id'] != user['id'] and user['role'] not in ('admin','manager'): conn.close(); raise HTTPException(403,'Not your session')
    is_correct = int(payload.selected == item['correct']); old_ability=float(sess['ability']); difficulty=float(item['difficulty'])
    new_ability = max(1.0,min(4.0, old_ability + (0.45 if is_correct else -0.35) + ((difficulty-old_ability)*0.08)))
    cur.execute('INSERT INTO responses(session_id,item_id,selected,correct,created_at) VALUES(?,?,?,?,?)',(payload.session_id,payload.item_id,payload.selected,is_correct,datetime.now(timezone.utc).isoformat()))
    cur.execute('UPDATE assessment_sessions SET ability=? WHERE id=?',(new_ability,payload.session_id)); conn.commit(); conn.close()
    nxt=get_next_item(payload.session_id)
    return {'correct': bool(is_correct), 'explanation': item['explanation'], 'ability': round(new_ability,2), 'next_item': nxt}


# --------------------------- Commercial helpers ---------------------------
def send_email(to_email: str, subject: str, body: str) -> bool:
    if not SMTP_HOST or not SMTP_USERNAME or not SMTP_PASSWORD:
        return False
    safe_subject = subject.replace('\r', '').replace('\n', ' ')
    safe_body = body.replace('\r\n', '\n')
    msg = f"From: {SMTP_FROM}\r\nTo: {to_email}\r\nSubject: {safe_subject}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{safe_body}"
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=12) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, [to_email], msg.encode('utf-8'))
        return True
    except Exception:
        return False

def product_name(product_id: str) -> str:
    for p in PRODUCTS:
        if p.get('id') == product_id:
            return p.get('name', product_id)
    return product_id.replace('-', ' ').title()

def activate_paid_access(customer_email: str, product_id: str):
    course_id = product_course(product_id)
    if not course_id:
        return {'activated': False, 'reason': 'No course mapped'}
    conn = db(); cur = conn.cursor()
    u = cur.execute('SELECT * FROM users WHERE email=?', (customer_email.lower(),)).fetchone()
    if not u:
        conn.close(); return {'activated': False, 'reason': 'Customer has not registered yet'}
    cur.execute('INSERT OR IGNORE INTO enrollments(user_id,name,email,course_id,status,created_at) VALUES(?,?,?,?,?,?)', (u['id'], u['name'], u['email'], course_id, 'active', datetime.now(timezone.utc).isoformat()))
    conn.commit(); conn.close()
    return {'activated': True, 'course_id': course_id}

# --------------------------- Commerce ---------------------------
PRODUCT_CONFIG = {
    'teacher-starter': {'amount': 1900, 'mode': 'payment', 'course_id': 'fcfp', 'description': 'Teacher Starter Bundle'},
    'teacher-certificate': {'amount': 19900, 'mode': 'payment', 'course_id': 'fcfp', 'description': 'Certified Finnish Paradigm Educator'},
    'early-intervention': {'amount': 4900, 'mode': 'payment', 'course_id': 'asti', 'description': 'Early Intervention Toolkit'},
    'retired-mentor': {'amount': 9900, 'mode': 'payment', 'course_id': 'asti', 'description': 'Retired Teacher Intervention Mentor Pack'},
    'school-leadership': {'amount': 14900, 'mode': 'payment', 'course_id': 'seld', 'description': 'School Leadership Implementation Pack'},
    'leadership-diploma': {'amount': 69900, 'mode': 'payment', 'course_id': 'seld', 'description': 'Strategic Educational Leadership Diploma'},
    'toolkit-bundle': {'amount': 4900, 'mode': 'payment', 'course_id': None, 'description': 'Full PDF Toolkit Bundle'},
    'membership-monthly': {'amount': 2900, 'mode': 'subscription', 'interval': 'month', 'course_id': 'fcfp', 'description': 'Monthly Teacher Membership'},
    'school-license': {'amount': 499900, 'mode': 'subscription', 'interval': 'year', 'course_id': 'seld', 'description': 'Annual Whole-School License'},
    'enterprise': {'amount': 0, 'mode': 'quote', 'course_id': None, 'description': 'Custom whole-school or ministry package'}
}

def stripe_enabled() -> bool:
    return bool(stripe and STRIPE_SECRET_KEY)

def product_amount(product_id: str) -> int:
    return PRODUCT_CONFIG.get(product_id, {'amount': 9900})['amount']

def product_mode(product_id: str) -> str:
    return PRODUCT_CONFIG.get(product_id, {'mode': 'payment'})['mode']

def product_course(product_id: str) -> Optional[str]:
    if product_id in PRODUCT_CONFIG:
        return PRODUCT_CONFIG[product_id].get('course_id')
    return None

def stripe_line_item(product_id: str, quantity: int, mode: str):
    price_id = STRIPE_PRICE_MAP.get(product_id)
    if price_id:
        return {'price': price_id, 'quantity': quantity}
    config = PRODUCT_CONFIG.get(product_id, {'amount': product_amount(product_id), 'description': product_name(product_id)})
    price_data = {
        'currency': STRIPE_CURRENCY,
        'unit_amount': int(config.get('amount', 9900)),
        'product_data': {'name': product_name(product_id), 'description': config.get('description', '')}
    }
    if mode == 'subscription':
        price_data['recurring'] = {'interval': config.get('interval', 'month')}
    return {'price_data': price_data, 'quantity': quantity}

def stripe_readiness_report():
    price_products = [k for k, v in PRODUCT_CONFIG.items() if v.get('mode') in ('payment', 'subscription')]
    missing_price_ids = [pid for pid in price_products if pid not in STRIPE_PRICE_MAP]
    return {
        'stripe_library_installed': bool(stripe),
        'secret_key_configured': bool(STRIPE_SECRET_KEY),
        'webhook_secret_configured': bool(STRIPE_WEBHOOK_SECRET),
        'checkout_modes_supported': ['payment', 'subscription'],
        'supported_events': ['checkout.session.completed','checkout.session.expired','checkout.session.async_payment_failed','payment_intent.payment_failed','charge.refunded','customer.subscription.created','customer.subscription.updated','customer.subscription.deleted','invoice.paid','invoice.payment_failed','charge.dispute.created'],
        'customer_portal_supported': True,
        'refunds_supported': True,
        'tax_automatic_enabled': STRIPE_TAX_AUTOMATIC,
        'promotion_codes_enabled': STRIPE_ALLOW_PROMOTION_CODES,
        'price_ids_configured_for': sorted(list(STRIPE_PRICE_MAP.keys())),
        'missing_price_ids_using_inline_price_data': missing_price_ids,
        'live_ready_after_owner_adds': ['STRIPE_SECRET_KEY','STRIPE_WEBHOOK_SECRET'] if not (STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET) else []
    }

@app.get('/api/stripe/readiness')
def stripe_readiness(user=Depends(require_admin)):
    return stripe_readiness_report()

@app.post('/api/checkout/create')
def create_checkout(payload: CheckoutIn):
    if payload.product_id not in PRODUCT_CONFIG and not any(p.get('id') == payload.product_id for p in PRODUCTS):
        raise HTTPException(404, 'Product not found')
    default_mode = product_mode(payload.product_id)
    if default_mode == 'quote':
        raise HTTPException(400, 'This product requires a consultation/quote rather than instant checkout')
    mode = payload.mode or default_mode
    if mode not in ('payment', 'subscription'):
        raise HTTPException(400, 'Checkout mode must be payment or subscription')
    amount = product_amount(payload.product_id) * payload.quantity
    conn=db(); cur=conn.cursor()
    meta = {'quantity': payload.quantity, 'mode': mode}
    cur.execute('''INSERT INTO orders(product_id,customer_email,amount,currency,status,checkout_url,provider_ref,created_at,payment_provider,mode,metadata)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(payload.product_id,payload.customer_email.lower(),amount,STRIPE_CURRENCY,'pending','', '',datetime.now(timezone.utc).isoformat(),'stripe',mode,json.dumps(meta)))
    conn.commit(); oid=cur.lastrowid
    success_url = payload.success_url or f'{PUBLIC_BASE_URL}/dashboard.html?payment=success&order_id={oid}&session_id={{CHECKOUT_SESSION_ID}}'
    cancel_url = payload.cancel_url or f'{PUBLIC_BASE_URL}/checkout.html?payment=cancelled&order_id={oid}'
    if stripe_enabled():
        try:
            params = {
                'mode': mode,
                'customer_email': payload.customer_email,
                'success_url': success_url,
                'cancel_url': cancel_url,
                'line_items': [stripe_line_item(payload.product_id, payload.quantity, mode)],
                'client_reference_id': str(oid),
                'metadata': {'order_id': str(oid), 'product_id': payload.product_id, 'customer_email': payload.customer_email.lower(), 'quantity': str(payload.quantity), 'mode': mode},
                'allow_promotion_codes': STRIPE_ALLOW_PROMOTION_CODES,
                'billing_address_collection': 'auto'
            }
            if STRIPE_TAX_AUTOMATIC:
                params['automatic_tax'] = {'enabled': True}
            if mode == 'subscription':
                params['subscription_data'] = {'metadata': {'order_id': str(oid), 'product_id': payload.product_id, 'customer_email': payload.customer_email.lower()}}
            session = stripe.checkout.Session.create(**params)
            checkout_url = session.url
            provider_ref = session.id
            status = 'stripe_checkout_created'
        except Exception as exc:
            checkout_url = f'{PUBLIC_BASE_URL}/checkout.html?product={payload.product_id}&email={payload.customer_email}&manual=1'
            provider_ref = 'stripe_error'
            status = 'stripe_error'
            cur.execute('UPDATE orders SET failure_reason=? WHERE id=?', (str(exc)[:500], oid))
    else:
        checkout_url = f'{PUBLIC_BASE_URL}/checkout.html?product={payload.product_id}&email={payload.customer_email}&manual=1'
        provider_ref = 'stripe_not_configured'
        status = 'stripe_not_configured'
    cur.execute('UPDATE orders SET status=?, checkout_url=?, provider_ref=? WHERE id=?', (status, checkout_url, provider_ref, oid))
    conn.commit(); conn.close()
    send_email(payload.customer_email, 'Finnish Paradigm order started', f'Your order reference is #{oid}. Continue here: {checkout_url}')
    return {'order_id':oid,'status':status,'checkout_url':checkout_url,'mode':mode,'amount':amount,'currency':STRIPE_CURRENCY,'stripe_ready':stripe_readiness_report()}

def record_payment_event(event: Dict[str, Any]):
    try:
        conn=db(); cur=conn.cursor()
        cur.execute('INSERT OR IGNORE INTO payment_events(event_id,event_type,provider_ref,payload,created_at) VALUES(?,?,?,?,?)', (event.get('id',''), event.get('type',''), (event.get('data') or {}).get('object',{}).get('id',''), json.dumps(event, default=str)[:20000], datetime.now(timezone.utc).isoformat()))
        conn.commit(); conn.close()
    except Exception:
        pass

def update_order_by_session(session, status: str):
    meta = session.get('metadata') or {}
    order_id = meta.get('order_id') or session.get('client_reference_id')
    if not order_id: return None
    conn=db(); cur=conn.cursor()
    cur.execute('''UPDATE orders SET status=?, provider_ref=?, stripe_customer_id=?, stripe_payment_intent=?, paid_at=CASE WHEN ?='paid' THEN ? ELSE paid_at END WHERE id=?''', (status, session.get('id',''), session.get('customer','') or '', session.get('payment_intent','') or '', status, datetime.now(timezone.utc).isoformat(), int(order_id)))
    conn.commit(); conn.close()
    return int(order_id)

@app.post('/api/stripe/webhook')
async def stripe_webhook(request: Request):
    body = await request.body()
    sig = request.headers.get('stripe-signature', '')
    if not (STRIPE_WEBHOOK_SECRET and stripe):
        raise HTTPException(400, 'Stripe webhook is not configured')
    try:
        event = stripe.Webhook.construct_event(body, sig, STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(400, 'Invalid webhook signature')
    record_payment_event(event)
    etype = event['type']
    obj = event['data']['object']
    if etype == 'checkout.session.completed':
        meta = obj.get('metadata') or {}
        update_order_by_session(obj, 'paid')
        product_id = meta.get('product_id')
        email = meta.get('customer_email') or obj.get('customer_email')
        if obj.get('mode') == 'subscription' and obj.get('subscription'):
            conn=db(); cur=conn.cursor(); now=datetime.now(timezone.utc).isoformat()
            cur.execute('''INSERT OR REPLACE INTO subscriptions(customer_email,product_id,stripe_customer_id,stripe_subscription_id,status,current_period_end,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)''', (email or '', product_id or '', obj.get('customer','') or '', obj.get('subscription',''), 'active', '', now, now))
            conn.commit(); conn.close()
        if email and product_id:
            activation = activate_paid_access(email, product_id)
            send_email(email, 'Finnish Paradigm course access', f'Payment confirmed. Access activation result: {activation}. Log in at {PUBLIC_BASE_URL}/login.html')
    elif etype in ('checkout.session.expired','checkout.session.async_payment_failed'):
        update_order_by_session(obj, 'failed' if 'failed' in etype else 'expired')
    elif etype == 'payment_intent.payment_failed':
        conn=db(); conn.execute('UPDATE orders SET status=?, failure_reason=? WHERE stripe_payment_intent=?', ('payment_failed', (obj.get('last_payment_error') or {}).get('message','payment failed'), obj.get('id',''))); conn.commit(); conn.close()
    elif etype == 'charge.refunded':
        payment_intent = obj.get('payment_intent','')
        refunded = int(obj.get('amount_refunded') or 0)
        conn=db(); conn.execute('UPDATE orders SET status=?, refunded_amount=?, refunded_at=? WHERE stripe_payment_intent=?', ('refunded', refunded, datetime.now(timezone.utc).isoformat(), payment_intent)); conn.commit(); conn.close()
    elif etype in ('customer.subscription.created','customer.subscription.updated','customer.subscription.deleted'):
        status = obj.get('status','')
        current_period_end = str(obj.get('current_period_end',''))
        sub_id = obj.get('id','')
        conn=db(); conn.execute('UPDATE subscriptions SET status=?, current_period_end=?, updated_at=? WHERE stripe_subscription_id=?', (status, current_period_end, datetime.now(timezone.utc).isoformat(), sub_id)); conn.commit(); conn.close()
    elif etype == 'invoice.payment_failed':
        customer = obj.get('customer','')
        conn=db(); conn.execute('UPDATE subscriptions SET status=?, updated_at=? WHERE stripe_customer_id=?', ('past_due', datetime.now(timezone.utc).isoformat(), customer)); conn.commit(); conn.close()
    elif etype == 'invoice.paid':
        customer = obj.get('customer','')
        conn=db(); conn.execute('UPDATE subscriptions SET status=?, updated_at=? WHERE stripe_customer_id=?', ('active', datetime.now(timezone.utc).isoformat(), customer)); conn.commit(); conn.close()
    elif etype == 'charge.dispute.created':
        payment_intent = obj.get('payment_intent','')
        conn=db(); conn.execute('UPDATE orders SET status=?, failure_reason=? WHERE stripe_payment_intent=?', ('disputed', 'Stripe dispute created', payment_intent)); conn.commit(); conn.close()
    return {'received': True, 'type': etype}

@app.post('/api/stripe/billing-portal')
def create_billing_portal(payload: BillingPortalIn, user=Depends(current_user)):
    if user['role'] not in ('admin','manager') and user['email'].lower() != payload.customer_email.lower():
        raise HTTPException(403, 'Cannot open billing portal for another customer')
    if not stripe_enabled():
        raise HTTPException(400, 'Stripe is not configured')
    conn=db(); row=conn.execute("SELECT stripe_customer_id FROM orders WHERE customer_email=? AND stripe_customer_id<>'' ORDER BY id DESC LIMIT 1", (payload.customer_email.lower(),)).fetchone(); conn.close()
    if not row:
        raise HTTPException(404, 'No Stripe customer found for this email yet')
    session = stripe.billing_portal.Session.create(customer=row['stripe_customer_id'], return_url=payload.return_url or STRIPE_BILLING_PORTAL_RETURN_URL)
    return {'url': session.url}

@app.post('/api/admin/orders/refund')
def refund_order(payload: RefundIn, user=Depends(require_admin)):
    if not stripe_enabled():
        raise HTTPException(400, 'Stripe is not configured')
    conn=db(); order=conn.execute('SELECT * FROM orders WHERE id=?', (payload.order_id,)).fetchone(); conn.close()
    if not order: raise HTTPException(404, 'Order not found')
    if not order['stripe_payment_intent']:
        raise HTTPException(400, 'Order has no Stripe payment intent to refund')
    params = {'payment_intent': order['stripe_payment_intent'], 'reason': payload.reason or 'requested_by_customer'}
    if payload.amount: params['amount'] = payload.amount
    refund = stripe.Refund.create(**params)
    conn=db(); conn.execute('UPDATE orders SET status=?, refunded_amount=?, refunded_at=? WHERE id=?', ('refund_requested', payload.amount or order['amount'], datetime.now(timezone.utc).isoformat(), payload.order_id)); conn.commit(); conn.close()
    return {'status':'refund_requested','refund_id':refund.id}

@app.get('/api/admin/orders')
def list_orders(user=Depends(require_admin)):
    conn=db(); rows=[dict(r) for r in conn.execute('SELECT * FROM orders ORDER BY id DESC')]; conn.close(); return rows

@app.get('/api/admin/subscriptions')
def list_subscriptions(user=Depends(require_admin)):
    conn=db(); rows=[dict(r) for r in conn.execute('SELECT * FROM subscriptions ORDER BY id DESC')]; conn.close(); return rows

@app.get('/api/admin/users')
def list_users(user=Depends(require_admin)):
    conn=db(); rows=[{k:v for k,v in dict(r).items() if k!='password_hash'} for r in conn.execute('SELECT * FROM users ORDER BY id DESC')]; conn.close(); return rows

# --------------------------- Admin API ---------------------------
@app.get('/api/admin/summary')
def admin_summary(user=Depends(require_admin)):
    conn=db(); cur=conn.cursor();
    keys = {'bookings':'bookings','enrollments':'enrollments','items':'items','assessment_sessions':'assessment_sessions','users':'users','open_cases':'intervention_cases'}
    out = {}
    for k,t in keys.items():
        if k == 'open_cases': out[k]=cur.execute("SELECT COUNT(*) FROM intervention_cases WHERE status='open'").fetchone()[0]
        else: out[k]=cur.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    out['orders'] = cur.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
    conn.close(); return out

@app.get('/api/admin/bookings')
def list_bookings(user=Depends(require_admin)):
    conn=db(); rows=[dict(r) for r in conn.execute('SELECT * FROM bookings ORDER BY id DESC')]; conn.close(); return rows

@app.get('/api/admin/enrollments')
def list_enrollments(user=Depends(require_admin)):
    conn=db(); rows=[dict(r) for r in conn.execute('SELECT * FROM enrollments ORDER BY id DESC')]; conn.close(); return rows

@app.post('/api/admin/item-bank')
def add_item(payload: ItemIn, user=Depends(require_admin)):
    conn=db(); cur=conn.cursor(); cur.execute('INSERT INTO items(course_id,difficulty,skill,question,options,correct,explanation) VALUES(?,?,?,?,?,?,?)',(payload.course_id,payload.difficulty,payload.skill,payload.question,json.dumps(payload.options),payload.correct,payload.explanation)); conn.commit(); ident=cur.lastrowid; conn.close(); return {'id':ident,'status':'created'}

@app.post('/api/admin/intervention-cases')
def create_case(payload: InterventionCaseIn, user=Depends(require_admin)):
    conn=db(); cur=conn.cursor(); now=datetime.now(timezone.utc).isoformat(); cur.execute('INSERT INTO intervention_cases(student_code,class_group,risk_level,concern,evidence,tier,status,assigned_to,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(payload.student_code,payload.class_group,payload.risk_level,payload.concern,payload.evidence,payload.tier,'open',payload.assigned_to,now,now)); conn.commit(); ident=cur.lastrowid; conn.close(); return {'id':ident,'status':'open'}

@app.get('/api/admin/intervention-cases')
def list_cases(user=Depends(require_admin)):
    conn=db(); rows=[dict(r) for r in conn.execute('SELECT * FROM intervention_cases ORDER BY id DESC')]; conn.close(); return rows

@app.patch('/api/admin/intervention-cases/{case_id}/close')
def close_case(case_id:int, user=Depends(require_admin)):
    conn=db(); cur=conn.cursor(); cur.execute("UPDATE intervention_cases SET status='closed', updated_at=? WHERE id=?",(datetime.now(timezone.utc).isoformat(),case_id)); conn.commit(); conn.close(); return {'status':'closed'}

# --------------------------- LMS Course/Module API ---------------------------
@app.get('/api/lms/courses')
def lms_courses():
    conn = db()
    rows = conn.execute('''
        SELECT c.course_id, c.slug, c.title, c.category, c.level, c.duration,
               c.cpd_hours, c.audience, c.aim, c.module_count,
               COUNT(m.id) AS actual_modules
        FROM lms_courses c
        LEFT JOIN lms_modules m ON m.course_id = c.course_id AND m.published = 1
        WHERE c.published = 1
        GROUP BY c.course_id
        ORDER BY c.id
    ''').fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get('/api/lms/courses/{course_id}')
def lms_course_detail(course_id: str):
    conn = db()
    course = conn.execute('SELECT * FROM lms_courses WHERE (course_id=? OR slug=?) AND published=1', (course_id, course_id)).fetchone()
    if not course:
        conn.close(); raise HTTPException(404, 'Course not found')
    modules = conn.execute('''
        SELECT module_id, title, scenario_setting, sort_order
        FROM lms_modules WHERE course_id=? AND published=1 ORDER BY sort_order
    ''', (course['course_id'],)).fetchall()
    conn.close()
    return {'course': dict(course), 'modules': [dict(m) for m in modules]}

@app.get('/api/lms/modules/{module_id}')
def lms_module_detail(module_id: str):
    conn = db()
    module = conn.execute('''
        SELECT m.*, c.title AS course_title, c.slug AS course_slug, c.course_id AS parent_course_id
        FROM lms_modules m JOIN lms_courses c ON c.course_id = m.course_id
        WHERE m.module_id=? AND m.published=1
    ''', (module_id,)).fetchone()
    if not module:
        conn.close(); raise HTTPException(404, 'Module not found')
    video = conn.execute('SELECT * FROM module_videos WHERE module_id=?', (module_id,)).fetchone()
    questions = conn.execute('SELECT question_id, question, question_type, answer_focus FROM lms_assessment_items WHERE module_id=? AND published=1', (module_id,)).fetchall()
    conn.close()
    return {
        'module': dict(module),
        'video': dict(video) if video else None,
        'assessment_items': [dict(q) for q in questions]
    }

@app.get('/api/lms/courses/{course_id}/assessments')
def lms_course_assessments(course_id: str):
    conn = db()
    rows = conn.execute('SELECT question_id, module_id, question, question_type, answer_focus FROM lms_assessment_items WHERE course_id=? AND published=1 ORDER BY module_id', (course_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

class LmsProgressUpdate(BaseModel):
    video_complete: Optional[bool] = None
    assessment_complete: Optional[bool] = None
    artifact_uploaded: Optional[bool] = None
    reflection_submitted: Optional[bool] = None

@app.post('/api/lms/progress/{course_id}/{module_id}')
def update_lms_progress(course_id: str, module_id: str, payload: LmsProgressUpdate, user=Depends(current_user)):
    conn = db(); cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    existing = cur.execute('SELECT id FROM learner_progress WHERE user_id=? AND course_id=? AND module_id=?', (user['id'], course_id, module_id)).fetchone()
    if not existing:
        cur.execute('INSERT INTO learner_progress(user_id, course_id, module_id, created_at, updated_at) VALUES(?,?,?,?,?)', (user['id'], course_id, module_id, now, now))
    updates = []
    params = []
    for field in ('video_complete', 'assessment_complete', 'artifact_uploaded', 'reflection_submitted'):
        val = getattr(payload, field)
        if val is not None:
            updates.append(f'{field}=?')
            params.append(int(val))
    if updates:
        params.append(now)
        params.extend([user['id'], course_id, module_id])
        cur.execute(f'UPDATE learner_progress SET {",".join(updates)}, updated_at=? WHERE user_id=? AND course_id=? AND module_id=?', params)
    row = cur.execute('SELECT video_complete, assessment_complete, artifact_uploaded, reflection_submitted FROM learner_progress WHERE user_id=? AND course_id=? AND module_id=?', (user['id'], course_id, module_id)).fetchone()
    is_complete = all(row[i] for i in range(4))
    cur.execute('UPDATE learner_progress SET module_complete=?, completed_at=CASE WHEN ? THEN ? ELSE completed_at END WHERE user_id=? AND course_id=? AND module_id=?', (int(is_complete), int(is_complete), now, user['id'], course_id, module_id))
    conn.commit(); conn.close()
    return {'status': 'progress_updated', 'module_complete': is_complete}

@app.get('/api/lms/progress/{course_id}')
def get_lms_progress(course_id: str, user=Depends(current_user)):
    conn = db()
    rows = conn.execute('SELECT * FROM learner_progress WHERE user_id=? AND course_id=?', (user['id'], course_id)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get('/api/lms/certificate/check/{course_id}')
def check_certificate(course_id: str, user=Depends(current_user)):
    conn = db()
    modules = conn.execute('SELECT module_id FROM lms_modules WHERE course_id=? AND published=1', (course_id,)).fetchall()
    if not modules:
        conn.close(); return {'eligible': False, 'reason': 'No modules found'}
    total = len(modules)
    completed = 0
    for m in modules:
        prog = conn.execute('SELECT module_complete FROM learner_progress WHERE user_id=? AND course_id=? AND module_id=?', (user['id'], course_id, m['module_id'])).fetchone()
        if prog and prog['module_complete']:
            completed += 1
    existing = conn.execute('SELECT certificate_id FROM certificates WHERE user_id=? AND course_id=? AND revoked=0', (user['id'], course_id)).fetchone()
    conn.close()
    return {'eligible': completed == total and total > 0, 'completed_modules': completed, 'total_modules': total, 'already_issued': bool(existing), 'certificate_id': existing['certificate_id'] if existing else None}

@app.post('/api/lms/certificate/issue/{course_id}')
def issue_certificate(course_id: str, user=Depends(current_user)):
    check = check_certificate(course_id, user)
    if not check['eligible']:
        raise HTTPException(400, f'Not eligible: {check["completed_modules"]}/{check["total_modules"]} modules completed')
    if check['already_issued']:
        return {'status': 'already_issued', 'certificate_id': check['certificate_id']}
    conn = db(); cur = conn.cursor()
    course = conn.execute('SELECT title, cpd_hours FROM lms_courses WHERE course_id=?', (course_id,)).fetchone()
    year = datetime.now(timezone.utc).year
    cert_id = f"FCEI-{course_id}-{year}-{user['id']:06d}"
    verification_url = f"{PUBLIC_BASE_URL}/verify-certificate/{cert_id}"
    certificate_url = f"{PUBLIC_BASE_URL}/certificates/{cert_id}.pdf"
    cur.execute('''INSERT OR IGNORE INTO certificates(certificate_id, user_id, course_id, learner_name, course_title, cpd_hours, certificate_url, verification_url, issued_at)
                   VALUES(?,?,?,?,?,?,?,?,?)''', (cert_id, user['id'], course_id, user['name'], course['title'], course['cpd_hours'], certificate_url, verification_url, datetime.now(timezone.utc).isoformat()))
    conn.commit(); conn.close()
    return {'status': 'issued', 'certificate_id': cert_id, 'certificate_url': certificate_url, 'verification_url': verification_url}

@app.get('/api/lms/certificates')
def my_certificates(user=Depends(current_user)):
    conn = db()
    rows = conn.execute('SELECT * FROM certificates WHERE user_id=? AND revoked=0 ORDER BY issued_at DESC', (user['id'],)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get('/api/admin/lms/stats')
def lms_stats(user=Depends(require_admin)):
    conn = db(); cur = conn.cursor()
    courses = cur.execute('SELECT COUNT(*) FROM lms_courses WHERE published=1').fetchone()[0]
    modules = cur.execute('SELECT COUNT(*) FROM lms_modules WHERE published=1').fetchone()[0]
    assessments = cur.execute('SELECT COUNT(*) FROM lms_assessment_items WHERE published=1').fetchone()[0]
    videos = cur.execute('SELECT COUNT(*) FROM module_videos').fetchone()[0]
    certificates = cur.execute('SELECT COUNT(*) FROM certificates WHERE revoked=0').fetchone()[0]
    progress_entries = cur.execute('SELECT COUNT(*) FROM learner_progress').fetchone()[0]
    conn.close()
    return {'lms_courses': courses, 'lms_modules': modules, 'assessment_items': assessments, 'video_entries': videos, 'certificates_issued': certificates, 'progress_entries': progress_entries}

# --------------------------- Files and front end ---------------------------
@app.get('/api/downloads/{filename}')
def download_file(filename: str):
    safe = os.path.basename(filename)
    path = os.path.join(STATIC_DIR, 'pdfs', safe)
    if not os.path.exists(path): raise HTTPException(404, 'File not found')
    return FileResponse(path, filename=safe)

app.mount('/', StaticFiles(directory=FRONTEND_DIR, html=True), name='frontend')
