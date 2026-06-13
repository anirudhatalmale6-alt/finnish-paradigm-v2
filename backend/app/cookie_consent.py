import os, json, hmac, hashlib, base64, time, secrets, sqlite3, re, uuid
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from collections import defaultdict
import threading
from fastapi import APIRouter, HTTPException, Depends, Header, Request
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, '..'))
DB_PATH = os.getenv('DATABASE_FILE', os.path.join(ROOT_DIR, 'data', 'finnish_paradigm.sqlite'))

def _get_jwt_secret():
    import backend.app.main as _main
    return _main.JWT_SECRET

DEFAULT_POLICY_VERSION = os.getenv('COOKIE_POLICY_VERSION', '2026-06-12-v1')
CONSENT_COOKIE_NAME = os.getenv('CONSENT_COOKIE_NAME', 'fcei_cookie_consent')
COOKIE_POLICY_URL = os.getenv('COOKIE_POLICY_URL', '/cookie-policy')
PRIVACY_POLICY_URL = os.getenv('PRIVACY_POLICY_URL', '/privacy-policy')
BANNER_TITLE = os.getenv('COOKIE_BANNER_TITLE', 'Your cookie choices')
BANNER_TEXT = os.getenv('COOKIE_BANNER_TEXT',
    'FCEI uses necessary cookies to make the platform work. With your choice, we can also use optional cookies for preferences, analytics and marketing.')
BRAND_LOGO_URL = os.getenv('COOKIE_BRAND_LOGO_URL', '')

ALLOWED_ACTIONS = {
    'accept_all', 'reject_optional', 'save_preferences',
    'withdraw_non_essential', 'admin_update', 'sync'
}

UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)

cookie_consent_router = APIRouter(prefix='/api/cookie-consent', tags=['Cookie Consent'])

def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))

def _read_token(token: str) -> Dict[str, Any]:
    try:
        jwt_secret = _get_jwt_secret()
        body, sig = token.split('.', 1)
        expected = _b64url(hmac.new(jwt_secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            raise ValueError('bad signature')
        payload = json.loads(_b64url_decode(body))
        if payload.get('exp', 0) < time.time():
            raise ValueError('expired')
        return payload
    except Exception:
        raise HTTPException(401, 'Invalid or expired token')

def _current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.lower().startswith('bearer '):
        raise HTTPException(401, 'Bearer token required')
    payload = _read_token(authorization.split(' ', 1)[1])
    conn = _db()
    user = conn.execute('SELECT id,name,email,role,organisation,active FROM users WHERE id=?', (payload['sub'],)).fetchone()
    conn.close()
    if not user or not user['active']:
        raise HTTPException(401, 'Account inactive')
    return dict(user)

def _require_admin(user=Depends(_current_user)):
    if user.get('role') != 'admin':
        raise HTTPException(403, 'Admin access required')
    return user

def _resolve_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.lower().startswith('bearer '):
        return None
    try:
        payload = _read_token(authorization.split(' ', 1)[1])
        conn = _db()
        user = conn.execute('SELECT id,name,email,role FROM users WHERE id=?', (payload['sub'],)).fetchone()
        conn.close()
        if user:
            return dict(user)
    except Exception:
        pass
    return None

def _safe_consent_id(value):
    if value and isinstance(value, str) and UUID_RE.match(value.strip()):
        return value.strip()
    return str(uuid.uuid4())

def _is_safe_link_url(value):
    if not value:
        return True
    v = str(value).strip()
    if v.startswith('/') or v.startswith('#'):
        return True
    m = re.match(r'^([a-zA-Z][a-zA-Z0-9+.-]*):', v)
    if not m:
        return True
    return m.group(1).lower() in ('http', 'https', 'mailto', 'tel')

def _is_safe_script_url(value):
    if not value:
        return True
    v = str(value).strip()
    try:
        from urllib.parse import urlparse
        u = urlparse(v)
        return u.scheme in ('http', 'https') and u.netloc != ''
    except Exception:
        return False

def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get('x-forwarded-for')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.client.host if request.client else '0.0.0.0'

_consent_write_limiter = defaultdict(list)
_limiter_lock = threading.Lock()

def _check_consent_rate(ip: str):
    now = time.time()
    with _limiter_lock:
        _consent_write_limiter[ip] = [t for t in _consent_write_limiter[ip] if t > now - 60]
        if len(_consent_write_limiter[ip]) >= 60:
            raise HTTPException(429, 'Too many requests')
        _consent_write_limiter[ip].append(now)

def _public_config():
    conn = _db()
    categories = conn.execute(
        "SELECT id, category_key, label, description, is_essential, default_enabled, display_order "
        "FROM cookie_consent_categories WHERE status='active' ORDER BY display_order ASC, label ASC"
    ).fetchall()
    services = conn.execute(
        "SELECT s.id, s.service_key, s.category_key, c.label AS category_label, s.name, s.provider, "
        "s.purpose, s.cookies, s.privacy_url, s.script_url, s.enabled, s.requires_consent "
        "FROM cookie_service_registry s "
        "JOIN cookie_consent_categories c ON c.category_key = s.category_key "
        "WHERE s.enabled = 1 AND c.status = 'active' "
        "ORDER BY c.display_order ASC, s.name ASC"
    ).fetchall()
    conn.close()

    cat_list = []
    for c in categories:
        cat_list.append({
            'id': c['id'],
            'category_key': c['category_key'],
            'label': c['label'],
            'description': c['description'],
            'is_essential': bool(c['is_essential']),
            'default_enabled': bool(c['default_enabled']),
            'display_order': c['display_order']
        })

    svc_list = []
    for s in services:
        cookies_raw = s['cookies']
        try:
            cookies = json.loads(cookies_raw) if cookies_raw else []
        except Exception:
            cookies = []
        svc_list.append({
            'id': s['id'],
            'service_key': s['service_key'],
            'category_key': s['category_key'],
            'category_label': s['category_label'],
            'name': s['name'],
            'provider': s['provider'],
            'purpose': s['purpose'],
            'cookies': cookies,
            'privacy_url': s['privacy_url'],
            'script_url': s['script_url'],
            'enabled': bool(s['enabled']),
            'requires_consent': bool(s['requires_consent'])
        })

    return {
        'policy_version': DEFAULT_POLICY_VERSION,
        'consent_cookie_name': CONSENT_COOKIE_NAME,
        'banner_title': BANNER_TITLE,
        'banner_text': BANNER_TEXT,
        'brand_logo_url': BRAND_LOGO_URL,
        'privacy_policy_url': PRIVACY_POLICY_URL,
        'cookie_policy_url': COOKIE_POLICY_URL,
        'categories': cat_list,
        'services': svc_list
    }


@cookie_consent_router.get('/config')
def get_config():
    return _public_config()


class ConsentRecordIn(BaseModel):
    consent_id: Optional[str] = None
    action: Optional[str] = 'save_preferences'
    choices: Optional[Dict[str, Any]] = {}

@cookie_consent_router.post('/record')
def record_consent(body: ConsentRecordIn, request: Request, user=Depends(_resolve_user)):
    _check_consent_rate(_get_client_ip(request))
    config = _public_config()
    cat_map = {c['category_key']: c for c in config['categories']}
    incoming = body.choices or {}
    choices = {}
    for cat in config['categories']:
        if cat['is_essential']:
            choices[cat['category_key']] = True
        else:
            val = incoming.get(cat['category_key'], False)
            choices[cat['category_key']] = bool(val)

    action = body.action or 'save_preferences'
    if action not in ALLOWED_ACTIONS:
        action = 'save_preferences'

    consent_id = _safe_consent_id(body.consent_id)
    user_id = user['id'] if user else None
    now = datetime.now(timezone.utc).isoformat()
    record_id = str(uuid.uuid4())

    conn = _db()
    conn.execute(
        "INSERT INTO cookie_consent_records "
        "(id, consent_id, user_id, policy_version, action, choices, categories_snapshot, services_snapshot, ip_address, user_agent, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (record_id, consent_id, user_id, config['policy_version'], action,
         json.dumps(choices), json.dumps(config['categories']), json.dumps(config['services']),
         _get_client_ip(request), request.headers.get('user-agent', ''), now)
    )
    conn.commit()
    conn.close()

    return {
        'ok': True,
        'consent': {
            'id': record_id,
            'consent_id': consent_id,
            'policy_version': config['policy_version'],
            'action': action,
            'choices': choices,
            'created_at': now
        },
        'choices': choices,
        'cookie_name': CONSENT_COOKIE_NAME
    }


@cookie_consent_router.post('/withdraw')
def withdraw_consent(body: ConsentRecordIn, request: Request, user=Depends(_resolve_user)):
    _check_consent_rate(_get_client_ip(request))
    config = _public_config()
    choices = {c['category_key']: bool(c['is_essential']) for c in config['categories']}
    consent_id = _safe_consent_id(body.consent_id)
    user_id = user['id'] if user else None
    now = datetime.now(timezone.utc).isoformat()
    record_id = str(uuid.uuid4())

    conn = _db()
    conn.execute(
        "INSERT INTO cookie_consent_records "
        "(id, consent_id, user_id, policy_version, action, choices, categories_snapshot, services_snapshot, ip_address, user_agent, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (record_id, consent_id, user_id, config['policy_version'], 'withdraw_non_essential',
         json.dumps(choices), json.dumps(config['categories']), json.dumps(config['services']),
         _get_client_ip(request), request.headers.get('user-agent', ''), now)
    )
    conn.commit()
    conn.close()

    return {
        'ok': True,
        'consent': {
            'id': record_id,
            'consent_id': consent_id,
            'policy_version': config['policy_version'],
            'action': 'withdraw_non_essential',
            'choices': choices,
            'created_at': now
        },
        'choices': choices,
        'cookie_name': CONSENT_COOKIE_NAME
    }


@cookie_consent_router.get('/admin/records')
def admin_records(limit: int = 100, user=Depends(_require_admin)):
    limit = min(limit, 500)
    conn = _db()
    rows = conn.execute(
        "SELECT r.id, r.consent_id, r.policy_version, r.action, r.choices, r.created_at, "
        "u.name AS full_name, u.email "
        "FROM cookie_consent_records r "
        "LEFT JOIN users u ON u.id = r.user_id "
        "ORDER BY r.created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    records = []
    for r in rows:
        choices_raw = r['choices']
        try:
            choices = json.loads(choices_raw) if choices_raw else {}
        except Exception:
            choices = {}
        records.append({
            'id': r['id'],
            'consent_id': r['consent_id'],
            'policy_version': r['policy_version'],
            'action': r['action'],
            'choices': choices,
            'created_at': r['created_at'],
            'full_name': r['full_name'],
            'email': r['email']
        })
    return {'records': records}


@cookie_consent_router.get('/admin/categories')
def admin_categories(user=Depends(_require_admin)):
    conn = _db()
    rows = conn.execute(
        "SELECT * FROM cookie_consent_categories ORDER BY display_order ASC, label ASC"
    ).fetchall()
    conn.close()
    return {'categories': [dict(r) for r in rows]}


class CategoryIn(BaseModel):
    category_key: str
    label: str
    description: str
    is_essential: Optional[bool] = False
    default_enabled: Optional[bool] = False
    display_order: Optional[int] = 1
    status: Optional[str] = 'active'

@cookie_consent_router.post('/admin/categories')
def admin_upsert_category(body: CategoryIn, user=Depends(_require_admin)):
    now = datetime.now(timezone.utc).isoformat()
    cat_id = str(uuid.uuid4())
    conn = _db()
    existing = conn.execute("SELECT id FROM cookie_consent_categories WHERE category_key=?", (body.category_key,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE cookie_consent_categories SET label=?, description=?, is_essential=?, default_enabled=?, "
            "display_order=?, status=?, updated_at=? WHERE category_key=?",
            (body.label, body.description, int(body.is_essential), int(body.default_enabled),
             body.display_order or 1, body.status or 'active', now, body.category_key)
        )
        cat_id = existing['id']
    else:
        conn.execute(
            "INSERT INTO cookie_consent_categories "
            "(id, category_key, label, description, is_essential, default_enabled, display_order, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (cat_id, body.category_key, body.label, body.description,
             int(body.is_essential), int(body.default_enabled),
             body.display_order or 1, body.status or 'active', now, now)
        )
    conn.commit()
    row = conn.execute("SELECT * FROM cookie_consent_categories WHERE id=?", (cat_id,)).fetchone()
    conn.close()
    return {'category': dict(row)}


@cookie_consent_router.get('/admin/services')
def admin_services(user=Depends(_require_admin)):
    conn = _db()
    rows = conn.execute(
        "SELECT * FROM cookie_service_registry ORDER BY category_key ASC, name ASC"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d['cookies'] = json.loads(d['cookies']) if d['cookies'] else []
        except Exception:
            d['cookies'] = []
        result.append(d)
    return {'services': result}


class ServiceIn(BaseModel):
    service_key: str
    category_key: str
    name: str
    provider: Optional[str] = None
    purpose: Optional[str] = None
    cookies: Optional[list] = []
    privacy_url: Optional[str] = None
    script_url: Optional[str] = None
    enabled: Optional[bool] = True
    requires_consent: Optional[bool] = True

@cookie_consent_router.post('/admin/services')
def admin_upsert_service(body: ServiceIn, user=Depends(_require_admin)):
    if not _is_safe_link_url(body.privacy_url):
        raise HTTPException(400, 'privacy_url uses an unsupported URL scheme')
    if not _is_safe_script_url(body.script_url):
        raise HTTPException(400, 'script_url must be an absolute http(s) URL')

    now = datetime.now(timezone.utc).isoformat()
    svc_id = str(uuid.uuid4())
    conn = _db()
    existing = conn.execute("SELECT id FROM cookie_service_registry WHERE service_key=?", (body.service_key,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE cookie_service_registry SET category_key=?, name=?, provider=?, purpose=?, cookies=?, "
            "privacy_url=?, script_url=?, enabled=?, requires_consent=?, updated_by=?, updated_at=? "
            "WHERE service_key=?",
            (body.category_key, body.name, body.provider, body.purpose,
             json.dumps(body.cookies or []),
             body.privacy_url, body.script_url,
             int(body.enabled if body.enabled is not None else True),
             int(body.requires_consent if body.requires_consent is not None else True),
             user['id'], now, body.service_key)
        )
        svc_id = existing['id']
    else:
        conn.execute(
            "INSERT INTO cookie_service_registry "
            "(id, service_key, category_key, name, provider, purpose, cookies, "
            "privacy_url, script_url, enabled, requires_consent, updated_by, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (svc_id, body.service_key, body.category_key, body.name,
             body.provider, body.purpose, json.dumps(body.cookies or []),
             body.privacy_url, body.script_url,
             int(body.enabled if body.enabled is not None else True),
             int(body.requires_consent if body.requires_consent is not None else True),
             user['id'], now, now)
        )
    conn.commit()
    row = conn.execute("SELECT * FROM cookie_service_registry WHERE id=?", (svc_id,)).fetchone()
    conn.close()
    d = dict(row)
    try:
        d['cookies'] = json.loads(d['cookies']) if d['cookies'] else []
    except Exception:
        d['cookies'] = []
    return {'service': d}


SEED_CATEGORIES = [
    {'category_key': 'strictly_necessary', 'label': 'Strictly Necessary', 'description': 'Essential cookies for login, security, payments, SCORM progress and your saved cookie choice. Cannot be disabled.', 'is_essential': True, 'default_enabled': True, 'display_order': 1},
    {'category_key': 'preferences', 'label': 'Preferences', 'description': 'Remember your settings like language, timezone and display preferences.', 'is_essential': False, 'default_enabled': False, 'display_order': 2},
    {'category_key': 'analytics', 'label': 'Analytics', 'description': 'Help us understand how visitors use the platform so we can improve it.', 'is_essential': False, 'default_enabled': False, 'display_order': 3},
    {'category_key': 'marketing', 'label': 'Marketing', 'description': 'Used to deliver relevant ads and measure campaign effectiveness.', 'is_essential': False, 'default_enabled': False, 'display_order': 4},
]

SEED_SERVICES = [
    {'service_key': 'fcei_platform', 'category_key': 'strictly_necessary', 'name': 'FCEI Platform', 'provider': 'FCEI', 'purpose': 'Authentication, session management, SCORM progress tracking and consent preferences.', 'cookies': [{'name': 'fcei_cookie_consent'}, {'name': 'fp_token'}], 'enabled': True, 'requires_consent': False},
    {'service_key': 'google_analytics', 'category_key': 'analytics', 'name': 'Google Analytics 4', 'provider': 'Google', 'purpose': 'Analytics reporting, if enabled by user consent.', 'cookies': [{'name': '_ga'}, {'name': '_gid'}], 'enabled': False, 'requires_consent': True},
    {'service_key': 'meta_pixel', 'category_key': 'marketing', 'name': 'Meta Pixel', 'provider': 'Meta', 'purpose': 'Conversion tracking for marketing campaigns.', 'cookies': [{'name': '_fbp'}, {'name': '_fbc'}], 'enabled': False, 'requires_consent': True},
]


def init_cookie_consent_tables():
    conn = _db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cookie_consent_categories (
            id TEXT PRIMARY KEY,
            category_key TEXT UNIQUE NOT NULL,
            label TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            is_essential INTEGER NOT NULL DEFAULT 0,
            default_enabled INTEGER NOT NULL DEFAULT 0,
            display_order INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cookie_service_registry (
            id TEXT PRIMARY KEY,
            service_key TEXT UNIQUE NOT NULL,
            category_key TEXT NOT NULL REFERENCES cookie_consent_categories(category_key),
            name TEXT NOT NULL,
            provider TEXT,
            purpose TEXT,
            cookies TEXT NOT NULL DEFAULT '[]',
            privacy_url TEXT,
            script_url TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            requires_consent INTEGER NOT NULL DEFAULT 1,
            updated_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_cookie_service_category ON cookie_service_registry(category_key, enabled);

        CREATE TABLE IF NOT EXISTS cookie_consent_records (
            id TEXT PRIMARY KEY,
            consent_id TEXT NOT NULL,
            user_id INTEGER REFERENCES users(id),
            policy_version TEXT NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('accept_all','reject_optional','save_preferences','withdraw_non_essential','admin_update','sync')),
            choices TEXT NOT NULL DEFAULT '{}',
            categories_snapshot TEXT NOT NULL DEFAULT '[]',
            services_snapshot TEXT NOT NULL DEFAULT '[]',
            ip_address TEXT,
            user_agent TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_cookie_consent_consent_id ON cookie_consent_records(consent_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_cookie_consent_user ON cookie_consent_records(user_id, created_at DESC);
    """)

    now = datetime.now(timezone.utc).isoformat()
    for cat in SEED_CATEGORIES:
        existing = conn.execute("SELECT id FROM cookie_consent_categories WHERE category_key=?", (cat['category_key'],)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO cookie_consent_categories (id, category_key, label, description, is_essential, default_enabled, display_order, status, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), cat['category_key'], cat['label'], cat['description'],
                 int(cat['is_essential']), int(cat['default_enabled']), cat['display_order'], 'active', now, now)
            )

    for svc in SEED_SERVICES:
        existing = conn.execute("SELECT id FROM cookie_service_registry WHERE service_key=?", (svc['service_key'],)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO cookie_service_registry (id, service_key, category_key, name, provider, purpose, cookies, privacy_url, script_url, enabled, requires_consent, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), svc['service_key'], svc['category_key'], svc['name'],
                 svc.get('provider'), svc.get('purpose'), json.dumps(svc.get('cookies', [])),
                 svc.get('privacy_url'), svc.get('script_url'),
                 int(svc.get('enabled', True)), int(svc.get('requires_consent', True)), now, now)
            )

    conn.commit()
    conn.close()
