import os, json, hmac, hashlib, base64, time, secrets, sqlite3, shutil, mimetypes
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Header, UploadFile, File, Form, Query
from fastapi.responses import FileResponse

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, '..'))
DB_PATH = os.getenv('DATABASE_FILE', os.path.join(ROOT_DIR, 'data', 'finnish_paradigm.sqlite'))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
def _get_jwt_secret():
    import backend.app.main as _main
    return _main.JWT_SECRET

TOOLKIT_STORAGE = os.path.join(os.path.dirname(STATIC_DIR), 'toolkit-storage')
os.makedirs(TOOLKIT_STORAGE, exist_ok=True)

MAX_ASSET_SIZE = 250 * 1024 * 1024

ALLOWED_ASSET_EXTENSIONS = {
    '.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.csv',
    '.zip', '.jpg', '.jpeg', '.png', '.webp',
}

toolkit_router = APIRouter(prefix='/api/toolkit-store', tags=['Toolkit Store'])

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
        raise HTTPException(401, 'User not found or inactive')
    return dict(user)

def _require_admin(user=Depends(_current_user)):
    if user['role'] not in ('admin', 'manager'):
        raise HTTPException(403, 'Admin or manager role required')
    return user

def _is_safe_url(value):
    if not value:
        return True
    v = str(value).strip()
    if v.startswith('/') or v.startswith('#'):
        return True
    import re
    m = re.match(r'^([a-zA-Z][a-zA-Z0-9+.-]*):', v)
    if not m:
        return True
    return m.group(1).lower() in ('http', 'https', 'mailto', 'tel')

def _non_neg_int(value, fallback=0):
    try:
        n = int(value)
        return max(0, n)
    except (TypeError, ValueError):
        return fallback

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def _money(row):
    d = dict(row)
    price = d.get('sale_price_cents') or d.get('price_cents', 0)
    currency = d.get('currency', 'GBP')
    d['display_price'] = f"{currency} {(price or 0) / 100:.2f}"
    d['effective_price_cents'] = price
    return d

def init_toolkit_tables():
    conn = _db()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS toolkit_products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_code TEXT UNIQUE NOT NULL,
        product_type TEXT NOT NULL DEFAULT 'single_module_toolkit',
        course_id TEXT,
        module_id TEXT,
        title TEXT NOT NULL,
        description TEXT,
        currency TEXT NOT NULL DEFAULT 'GBP',
        price_cents INTEGER NOT NULL DEFAULT 0,
        sale_price_cents INTEGER,
        tax_category TEXT DEFAULT 'digital_goods',
        access_scope TEXT NOT NULL DEFAULT 'module',
        requires_enrollment INTEGER NOT NULL DEFAULT 0,
        included_product_codes TEXT NOT NULL DEFAULT '[]',
        thumbnail_url TEXT,
        preview_url TEXT,
        scorm_toolkit_zip TEXT,
        status TEXT NOT NULL DEFAULT 'draft',
        sort_order INTEGER NOT NULL DEFAULT 1,
        created_by INTEGER,
        updated_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS toolkit_product_assets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL REFERENCES toolkit_products(id) ON DELETE CASCADE,
        asset_type TEXT NOT NULL DEFAULT 'pdf',
        title TEXT NOT NULL,
        description TEXT,
        storage_key TEXT,
        original_filename TEXT,
        stored_filename TEXT,
        public_url TEXT,
        mime_type TEXT,
        file_size_bytes INTEGER NOT NULL DEFAULT 0,
        version_label TEXT NOT NULL DEFAULT 'v1.0',
        is_primary INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'published',
        created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS toolkit_orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number TEXT UNIQUE NOT NULL,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        status TEXT NOT NULL DEFAULT 'pending',
        currency TEXT NOT NULL DEFAULT 'GBP',
        subtotal_cents INTEGER NOT NULL DEFAULT 0,
        discount_cents INTEGER NOT NULL DEFAULT 0,
        tax_cents INTEGER NOT NULL DEFAULT 0,
        total_cents INTEGER NOT NULL DEFAULT 0,
        payment_provider TEXT NOT NULL DEFAULT 'manual',
        provider_checkout_id TEXT,
        provider_payment_id TEXT,
        checkout_url TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        paid_at TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS toolkit_order_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL REFERENCES toolkit_orders(id) ON DELETE CASCADE,
        product_id INTEGER NOT NULL REFERENCES toolkit_products(id),
        product_code TEXT NOT NULL,
        title TEXT NOT NULL,
        unit_price_cents INTEGER NOT NULL DEFAULT 0,
        quantity INTEGER NOT NULL DEFAULT 1,
        line_total_cents INTEGER NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS toolkit_entitlements(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        product_id INTEGER NOT NULL REFERENCES toolkit_products(id) ON DELETE CASCADE,
        source_order_id INTEGER REFERENCES toolkit_orders(id) ON DELETE SET NULL,
        entitlement_scope TEXT NOT NULL DEFAULT 'module',
        course_id TEXT,
        module_id TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        granted_by INTEGER,
        granted_at TEXT DEFAULT CURRENT_TIMESTAMP,
        expires_at TEXT,
        UNIQUE(user_id, product_id)
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS toolkit_download_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        asset_id INTEGER,
        ip_address TEXT,
        user_agent TEXT,
        downloaded_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_tk_products_status ON toolkit_products(status)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_tk_products_course ON toolkit_products(course_id, module_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_tk_assets_product ON toolkit_product_assets(product_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_tk_orders_user ON toolkit_orders(user_id, status)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_tk_entitlements_user ON toolkit_entitlements(user_id, status)')
    conn.commit()
    conn.close()


def _get_products(conn, include_draft=False, course_id=None, module_id=None, course_code=None, module_code=None):
    sql = 'SELECT * FROM toolkit_products WHERE 1=1'
    params = []
    if not include_draft:
        sql += " AND status='published'"
    if course_id:
        sql += ' AND course_id=?'
        params.append(course_id)
    if module_id:
        sql += ' AND module_id=?'
        params.append(module_id)
    if course_code:
        sql += ' AND product_code LIKE ?'
        params.append(f'TK-{course_code}-%')
    if module_code:
        sql += ' AND product_code LIKE ?'
        params.append(f'%-{module_code}%')
    sql += ' ORDER BY sort_order, id'
    rows = conn.execute(sql, params).fetchall()
    return [_money(r) for r in rows]


def _has_toolkit_access(conn, user_id, product):
    ent = conn.execute(
        "SELECT id FROM toolkit_entitlements WHERE user_id=? AND product_id=? AND status='active' AND (expires_at IS NULL OR expires_at > ?)",
        (user_id, product['id'], _now_iso())
    ).fetchone()
    if ent:
        return True
    scope = product.get('access_scope', 'module')
    if scope == 'module' and product.get('course_id'):
        lib = conn.execute(
            "SELECT te.id FROM toolkit_entitlements te JOIN toolkit_products tp ON tp.id=te.product_id WHERE te.user_id=? AND te.status='active' AND (te.expires_at IS NULL OR te.expires_at > ?) AND tp.access_scope IN ('library','institution')",
            (user_id, _now_iso())
        ).fetchone()
        if lib:
            return True
        course_ent = conn.execute(
            "SELECT te.id FROM toolkit_entitlements te JOIN toolkit_products tp ON tp.id=te.product_id WHERE te.user_id=? AND te.status='active' AND (te.expires_at IS NULL OR te.expires_at > ?) AND tp.access_scope='course' AND tp.course_id=?",
            (user_id, _now_iso(), product['course_id'])
        ).fetchone()
        if course_ent:
            return True
    elif scope == 'course' and product.get('course_id'):
        lib = conn.execute(
            "SELECT te.id FROM toolkit_entitlements te JOIN toolkit_products tp ON tp.id=te.product_id WHERE te.user_id=? AND te.status='active' AND (te.expires_at IS NULL OR te.expires_at > ?) AND tp.access_scope IN ('library','institution')",
            (user_id, _now_iso())
        ).fetchone()
        if lib:
            return True
    code = product.get('product_code', '')
    bundles = conn.execute(
        "SELECT tp.included_product_codes FROM toolkit_entitlements te JOIN toolkit_products tp ON tp.id=te.product_id WHERE te.user_id=? AND te.status='active' AND (te.expires_at IS NULL OR te.expires_at > ?) AND tp.included_product_codes != '[]'",
        (user_id, _now_iso())
    ).fetchall()
    for b in bundles:
        codes = json.loads(b['included_product_codes'] or '[]')
        if code in codes:
            return True
    return False


def _grant_entitlements_for_order(conn, order_id, actor_id):
    items = conn.execute('SELECT oi.*, tp.access_scope, tp.course_id, tp.module_id FROM toolkit_order_items oi JOIN toolkit_products tp ON tp.id=oi.product_id WHERE oi.order_id=?', (order_id,)).fetchall()
    now = _now_iso()
    for item in items:
        conn.execute('''INSERT INTO toolkit_entitlements(user_id, product_id, source_order_id, entitlement_scope, course_id, module_id, status, granted_by, granted_at)
            VALUES(?,?,?,?,?,?,'active',?,?)
            ON CONFLICT(user_id, product_id) DO UPDATE SET status='active', source_order_id=excluded.source_order_id, granted_by=excluded.granted_by, granted_at=excluded.granted_at''',
            (actor_id, item['product_id'], order_id, item['access_scope'], item['course_id'], item['module_id'], actor_id, now))
    conn.commit()


# ─── Public endpoints ───

@toolkit_router.get('/public/options')
def public_options(course_id: Optional[str] = None, module_id: Optional[str] = None,
                   course_code: Optional[str] = None, module_code: Optional[str] = None):
    conn = _db()
    products = _get_products(conn, include_draft=False, course_id=course_id, module_id=module_id, course_code=course_code, module_code=module_code)
    conn.close()
    return {'products': products}

# ─── Learner endpoints ───

@toolkit_router.get('/learner/options')
def learner_options(course_id: Optional[str] = None, module_id: Optional[str] = None,
                    course_code: Optional[str] = None, module_code: Optional[str] = None,
                    user=Depends(_current_user)):
    conn = _db()
    products = _get_products(conn, include_draft=False, course_id=course_id, module_id=module_id, course_code=course_code, module_code=module_code)
    for p in products:
        p['has_access'] = _has_toolkit_access(conn, user['id'], p)
    conn.close()
    return {'products': products}

@toolkit_router.get('/learner/library')
def learner_library(user=Depends(_current_user)):
    conn = _db()
    rows = conn.execute('''SELECT te.*, tp.product_code, tp.title, tp.product_type, tp.access_scope AS product_scope,
        tp.currency, tp.price_cents, tp.sale_price_cents, tp.thumbnail_url,
        (SELECT COUNT(*) FROM toolkit_product_assets WHERE product_id=tp.id AND status='published') AS asset_count
        FROM toolkit_entitlements te JOIN toolkit_products tp ON tp.id=te.product_id
        WHERE te.user_id=? AND te.status='active' AND (te.expires_at IS NULL OR te.expires_at > ?)
        ORDER BY te.granted_at DESC''', (user['id'], _now_iso())).fetchall()
    conn.close()
    return {'entitlements': [dict(r) for r in rows]}

@toolkit_router.post('/checkout')
def checkout(body: dict, user=Depends(_current_user)):
    product_ids = body.get('product_ids', [])
    if not product_ids:
        raise HTTPException(400, 'product_ids required')
    conn = _db()
    try:
        products = []
        for pid in product_ids:
            p = conn.execute("SELECT * FROM toolkit_products WHERE id=? AND status='published'", (pid,)).fetchone()
            if not p:
                raise HTTPException(400, f'Product {pid} not found or unavailable')
            products.append(dict(p))
        now = _now_iso()
        order_number = f"FCEI-TK-{int(time.time())}-{secrets.token_hex(4).upper()}"
        subtotal = sum((p.get('sale_price_cents') or p['price_cents']) for p in products)
        conn.execute('''INSERT INTO toolkit_orders(order_number, user_id, status, currency, subtotal_cents, total_cents, payment_provider, created_at, updated_at)
            VALUES(?,?,'pending',?,?,?,'stripe',?,?)''',
            (order_number, user['id'], products[0].get('currency', 'GBP'), subtotal, subtotal, now, now))
        order_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        for p in products:
            price = p.get('sale_price_cents') or p['price_cents']
            conn.execute('''INSERT INTO toolkit_order_items(order_id, product_id, product_code, title, unit_price_cents, quantity, line_total_cents, created_at)
                VALUES(?,?,?,?,?,1,?,?)''',
                (order_id, p['id'], p['product_code'], p['title'], price, price, now))
        conn.commit()
        checkout_url = body.get('success_url', f'/dashboard.html?toolkit_order={order_id}')
        conn.close()
        return {'order': {'id': order_id, 'order_number': order_number, 'total_cents': subtotal, 'status': 'pending'}, 'checkout_url': checkout_url}
    except HTTPException:
        conn.close()
        raise
    except Exception as e:
        conn.close()
        raise HTTPException(500, str(e))

@toolkit_router.post('/checkout/{order_id}/demo-complete')
def demo_complete(order_id: int, user=Depends(_current_user)):
    env = os.getenv('NODE_ENV', os.getenv('ENVIRONMENT', 'development'))
    if env == 'production':
        raise HTTPException(403, 'Demo checkout disabled in production')
    conn = _db()
    order = conn.execute('SELECT * FROM toolkit_orders WHERE id=? AND user_id=?', (order_id, user['id'])).fetchone()
    if not order:
        raise HTTPException(404, 'Order not found')
    now = _now_iso()
    conn.execute("UPDATE toolkit_orders SET status='paid', paid_at=?, updated_at=? WHERE id=?", (now, now, order_id))
    _grant_entitlements_for_order(conn, order_id, user['id'])
    conn.close()
    return {'ok': True, 'message': 'Demo payment complete. Toolkit access granted.'}

@toolkit_router.get('/learner/products/{product_id}/assets')
def learner_assets(product_id: int, user=Depends(_current_user)):
    conn = _db()
    product = conn.execute('SELECT * FROM toolkit_products WHERE id=?', (product_id,)).fetchone()
    if not product:
        conn.close()
        raise HTTPException(404, 'Product not found')
    if not _has_toolkit_access(conn, user['id'], dict(product)):
        conn.close()
        raise HTTPException(403, 'You do not have access to this product')
    assets = conn.execute("SELECT id, asset_type, title, description, original_filename, public_url, version_label, is_primary, file_size_bytes FROM toolkit_product_assets WHERE product_id=? AND status='published' ORDER BY is_primary DESC, id", (product_id,)).fetchall()
    conn.close()
    return {'assets': [dict(a) for a in assets]}

@toolkit_router.get('/learner/products/{product_id}/assets/{asset_id}/download')
def learner_download(product_id: int, asset_id: int, request: Any = None, user=Depends(_current_user)):
    conn = _db()
    product = conn.execute('SELECT * FROM toolkit_products WHERE id=?', (product_id,)).fetchone()
    if not product:
        conn.close()
        raise HTTPException(404, 'Product not found')
    if not _has_toolkit_access(conn, user['id'], dict(product)):
        conn.close()
        raise HTTPException(403, 'Access denied')
    asset = conn.execute('SELECT * FROM toolkit_product_assets WHERE id=? AND product_id=?', (asset_id, product_id)).fetchone()
    if not asset:
        conn.close()
        raise HTTPException(404, 'Asset not found')
    conn.execute('INSERT INTO toolkit_download_logs(user_id, product_id, asset_id, downloaded_at) VALUES(?,?,?,?)',
        (user['id'], product_id, asset_id, _now_iso()))
    conn.commit()
    if asset['public_url'] and _is_safe_url(asset['public_url']):
        conn.close()
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=asset['public_url'])
    if asset['stored_filename']:
        fpath = os.path.join(TOOLKIT_STORAGE, asset['stored_filename'])
        real = os.path.realpath(fpath)
        if not real.startswith(os.path.realpath(TOOLKIT_STORAGE) + os.sep):
            conn.close()
            raise HTTPException(403, 'Invalid path')
        if os.path.isfile(real):
            conn.close()
            return FileResponse(real, filename=asset['original_filename'] or asset['stored_filename'],
                                media_type=asset['mime_type'] or 'application/octet-stream')
    conn.close()
    raise HTTPException(404, 'Asset file not available')

# ─── Admin endpoints ───

@toolkit_router.get('/admin/products')
def admin_products(course_id: Optional[str] = None, module_id: Optional[str] = None,
                   course_code: Optional[str] = None, module_code: Optional[str] = None,
                   user=Depends(_require_admin)):
    conn = _db()
    products = _get_products(conn, include_draft=True, course_id=course_id, module_id=module_id, course_code=course_code, module_code=module_code)
    for p in products:
        p['asset_count'] = conn.execute('SELECT COUNT(*) FROM toolkit_product_assets WHERE product_id=?', (p['id'],)).fetchone()[0]
    conn.close()
    return {'products': products}

@toolkit_router.post('/admin/products')
def admin_create_product(body: dict, user=Depends(_require_admin)):
    required = ['product_code', 'title']
    for f in required:
        if not body.get(f):
            raise HTTPException(400, f'{f} is required')
    if not _is_safe_url(body.get('thumbnail_url')):
        raise HTTPException(400, 'thumbnail_url uses an unsupported URL scheme')
    if not _is_safe_url(body.get('preview_url')):
        raise HTTPException(400, 'preview_url uses an unsupported URL scheme')
    conn = _db()
    existing = conn.execute('SELECT id FROM toolkit_products WHERE product_code=?', (body['product_code'],)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(409, f"Product code {body['product_code']} already exists")
    now = _now_iso()
    included = json.dumps(body.get('included_product_codes', []))
    conn.execute('''INSERT INTO toolkit_products(product_code, product_type, course_id, module_id, title, description,
        currency, price_cents, sale_price_cents, tax_category, access_scope, requires_enrollment,
        included_product_codes, thumbnail_url, preview_url, scorm_toolkit_zip, status, sort_order,
        created_by, updated_by, created_at, updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (body['product_code'], body.get('product_type', 'single_module_toolkit'),
         body.get('course_id'), body.get('module_id'), body['title'], body.get('description', ''),
         body.get('currency', 'GBP'), _non_neg_int(body.get('price_cents', 0)),
         body.get('sale_price_cents'), body.get('tax_category', 'digital_goods'),
         body.get('access_scope', 'module'), 1 if body.get('requires_enrollment') else 0,
         included, body.get('thumbnail_url'), body.get('preview_url'),
         body.get('scorm_toolkit_zip', ''), body.get('status', 'draft'),
         _non_neg_int(body.get('sort_order', 1)), user['id'], user['id'], now, now))
    pid = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.commit()
    conn.close()
    return {'id': pid, 'product_code': body['product_code']}

@toolkit_router.patch('/admin/products/{product_id}')
def admin_update_product(product_id: int, body: dict, user=Depends(_require_admin)):
    conn = _db()
    existing = conn.execute('SELECT * FROM toolkit_products WHERE id=?', (product_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, 'Product not found')
    if not _is_safe_url(body.get('thumbnail_url', existing['thumbnail_url'])):
        raise HTTPException(400, 'thumbnail_url uses an unsupported URL scheme')
    if not _is_safe_url(body.get('preview_url', existing['preview_url'])):
        raise HTTPException(400, 'preview_url uses an unsupported URL scheme')
    now = _now_iso()
    fields = {
        'product_code': body.get('product_code', existing['product_code']),
        'product_type': body.get('product_type', existing['product_type']),
        'course_id': body.get('course_id', existing['course_id']),
        'module_id': body.get('module_id', existing['module_id']),
        'title': body.get('title', existing['title']),
        'description': body.get('description', existing['description']),
        'currency': body.get('currency', existing['currency']),
        'price_cents': _non_neg_int(body.get('price_cents', existing['price_cents'])),
        'sale_price_cents': body.get('sale_price_cents', existing['sale_price_cents']),
        'access_scope': body.get('access_scope', existing['access_scope']),
        'requires_enrollment': 1 if body.get('requires_enrollment', existing['requires_enrollment']) else 0,
        'included_product_codes': json.dumps(body['included_product_codes']) if 'included_product_codes' in body else existing['included_product_codes'],
        'thumbnail_url': body.get('thumbnail_url', existing['thumbnail_url']),
        'preview_url': body.get('preview_url', existing['preview_url']),
        'scorm_toolkit_zip': body.get('scorm_toolkit_zip', existing['scorm_toolkit_zip']),
        'status': body.get('status', existing['status']),
        'sort_order': _non_neg_int(body.get('sort_order', existing['sort_order'])),
        'updated_by': user['id'],
        'updated_at': now,
    }
    sets = ', '.join(f'{k}=?' for k in fields)
    conn.execute(f'UPDATE toolkit_products SET {sets} WHERE id=?', list(fields.values()) + [product_id])
    conn.commit()
    conn.close()
    return {'ok': True}

@toolkit_router.post('/admin/products/{product_id}/assets')
async def admin_upload_asset(product_id: int,
                             asset: UploadFile = File(...),
                             asset_type: str = Form('pdf'),
                             title: str = Form(''),
                             description: str = Form(''),
                             public_url: str = Form(''),
                             version_label: str = Form('v1.0'),
                             is_primary: int = Form(0),
                             status: str = Form('published'),
                             user=Depends(_require_admin)):
    conn = _db()
    product = conn.execute('SELECT id FROM toolkit_products WHERE id=?', (product_id,)).fetchone()
    if not product:
        conn.close()
        raise HTTPException(404, 'Product not found')
    if public_url and not _is_safe_url(public_url):
        conn.close()
        raise HTTPException(400, 'public_url uses an unsupported URL scheme')
    ext = os.path.splitext(asset.filename or '')[1].lower()
    if ext and ext not in ALLOWED_ASSET_EXTENSIONS:
        conn.close()
        raise HTTPException(400, f'File type {ext} not allowed')
    stored_name = f"{secrets.token_hex(12)}{ext}"
    fpath = os.path.join(TOOLKIT_STORAGE, stored_name)
    content = await asset.read()
    if len(content) > MAX_ASSET_SIZE:
        conn.close()
        raise HTTPException(413, 'File too large')
    with open(fpath, 'wb') as f:
        f.write(content)
    mime = mimetypes.guess_type(asset.filename or '')[0] or 'application/octet-stream'
    now = _now_iso()
    conn.execute('''INSERT INTO toolkit_product_assets(product_id, asset_type, title, description, storage_key, original_filename,
        stored_filename, public_url, mime_type, file_size_bytes, version_label, is_primary, status, created_by, created_at, updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (product_id, asset_type, title or asset.filename, description, stored_name, asset.filename,
         stored_name, public_url, mime, len(content), version_label, is_primary, status, user['id'], now, now))
    conn.commit()
    aid = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return {'id': aid, 'filename': asset.filename, 'size': len(content)}

@toolkit_router.get('/admin/orders')
def admin_orders(user=Depends(_require_admin)):
    conn = _db()
    rows = conn.execute('''SELECT o.*, u.name AS user_name, u.email AS user_email,
        (SELECT COUNT(*) FROM toolkit_order_items WHERE order_id=o.id) AS item_count
        FROM toolkit_orders o JOIN users u ON u.id=o.user_id
        ORDER BY o.created_at DESC LIMIT 500''').fetchall()
    conn.close()
    return {'orders': [dict(r) for r in rows]}

@toolkit_router.post('/admin/entitlements/grant')
def admin_grant(body: dict, user=Depends(_require_admin)):
    uid = body.get('user_id')
    pid = body.get('product_id')
    if not uid or not pid:
        raise HTTPException(400, 'user_id and product_id required')
    conn = _db()
    product = conn.execute('SELECT * FROM toolkit_products WHERE id=?', (pid,)).fetchone()
    if not product:
        conn.close()
        raise HTTPException(404, 'Product not found')
    target = conn.execute('SELECT id FROM users WHERE id=?', (uid,)).fetchone()
    if not target:
        conn.close()
        raise HTTPException(404, 'User not found')
    now = _now_iso()
    conn.execute('''INSERT INTO toolkit_entitlements(user_id, product_id, entitlement_scope, course_id, module_id, status, granted_by, granted_at, expires_at)
        VALUES(?,?,?,?,?,'active',?,?,?)
        ON CONFLICT(user_id, product_id) DO UPDATE SET status='active', granted_by=excluded.granted_by, granted_at=excluded.granted_at, expires_at=excluded.expires_at''',
        (uid, pid, product['access_scope'], product['course_id'], product['module_id'], user['id'], now, body.get('expires_at')))
    conn.commit()
    conn.close()
    return {'ok': True, 'message': f'Entitlement granted to user {uid} for product {pid}'}
