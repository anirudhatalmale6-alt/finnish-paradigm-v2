
import os, json, hmac, hashlib, base64, time, secrets, sqlite3, mimetypes, re
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Depends, Header, Request, UploadFile, File, Form, Query
from fastapi.responses import FileResponse, Response

# ─── Paths & config ───

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, '..'))
DB_PATH = os.getenv('DATABASE_FILE', os.path.join(ROOT_DIR, 'data', 'finnish_paradigm.sqlite'))
STATIC_DIR = os.path.join(BASE_DIR, 'static')

CMS_STORAGE = os.path.join(os.path.dirname(STATIC_DIR), 'cms-storage')
CMS_MEDIA_DIR = os.path.join(CMS_STORAGE, 'media')
os.makedirs(CMS_MEDIA_DIR, exist_ok=True)

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB

ALLOWED_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg',
    '.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.csv', '.txt',
    '.mp4', '.webm', '.mov', '.vtt',
}

DANGEROUS_SCHEMES = {'javascript', 'data', 'vbscript'}

# ─── Router ───

cms_router = APIRouter(prefix='/api/cms', tags=['CMS'])

# ─── DB + Auth (self-contained, same logic as main.py / scorm.py) ───


def _get_jwt_secret():
    import backend.app.main as _main
    return _main.JWT_SECRET


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
    user = conn.execute(
        'SELECT id,name,email,role,organisation,active FROM users WHERE id=?',
        (payload['sub'],),
    ).fetchone()
    conn.close()
    if not user or not user['active']:
        raise HTTPException(401, 'User not found or inactive')
    return dict(user)


def _optional_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.lower().startswith('bearer '):
        return None
    try:
        payload = _read_token(authorization.split(' ', 1)[1])
        conn = _db()
        user = conn.execute(
            'SELECT id,name,email,role,organisation,active FROM users WHERE id=?',
            (payload['sub'],),
        ).fetchone()
        conn.close()
        if not user or not user['active']:
            return None
        return dict(user)
    except Exception:
        return None


def _require_admin(user=Depends(_current_user)):
    if user['role'] not in ('admin', 'manager'):
        raise HTTPException(403, 'Admin or manager role required')
    return user


# ─── Helpers ───

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_url(url: str, field_name: str = 'url') -> str:
    """Block dangerous URI schemes. Returns the url if safe."""
    if not url:
        return url
    stripped = url.strip()
    # Check scheme
    try:
        parsed = urlparse(stripped)
        if parsed.scheme and parsed.scheme.lower() in DANGEROUS_SCHEMES:
            raise HTTPException(400, f'{field_name} contains a blocked URI scheme: {parsed.scheme}')
    except ValueError:
        raise HTTPException(400, f'{field_name} is not a valid URL')
    # Extra safety: check the raw string for obfuscated javascript: etc.
    lower = stripped.lower().replace('\t', '').replace('\n', '').replace('\r', '').replace(' ', '')
    for scheme in DANGEROUS_SCHEMES:
        if lower.startswith(scheme + ':'):
            raise HTTPException(400, f'{field_name} contains a blocked URI scheme')
    return stripped


def _validate_extension(filename: str) -> str:
    """Validate file extension against whitelist. Returns lowercased extension."""
    if not filename:
        raise HTTPException(400, 'Filename is required')
    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f'File type {ext!r} is not allowed. Permitted: {", ".join(sorted(ALLOWED_EXTENSIONS))}',
        )
    return ext


def _safe_filename(original: str) -> str:
    """Sanitise filename for storage."""
    name = os.path.basename(original)
    name = re.sub(r'[^\w.\-]', '_', name)
    return name


def _row_to_dict(row) -> Optional[dict]:
    if row is None:
        return None
    return dict(row)


def _rows_to_list(rows) -> List[dict]:
    return [dict(r) for r in rows]


def _parse_json_field(value: Optional[str]) -> Any:
    """Parse a TEXT column that stores JSON. Return None for empty/null."""
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _enrich_page_dict(page: dict) -> dict:
    """Parse JSON fields in a page dict for API response."""
    return page


def _enrich_section_dict(section: dict) -> dict:
    """Parse the config JSON field."""
    if section and section.get('config'):
        section['config'] = _parse_json_field(section['config'])
    return section


def _enrich_setting_dict(setting: dict) -> dict:
    """Parse setting_value if it looks like JSON."""
    if setting and setting.get('setting_value'):
        setting['setting_value'] = _parse_json_field(setting['setting_value'])
    return setting


def _save_revision(conn, entity_type: str, entity_id: int, snapshot: dict, note: str, user_id: int):
    """Save a revision snapshot before modification."""
    conn.execute(
        '''INSERT INTO cms_revisions(entity_type, entity_id, snapshot, revision_note, created_by, created_at)
           VALUES(?,?,?,?,?,?)''',
        (entity_type, entity_id, json.dumps(snapshot, default=str), note, user_id, _utcnow()),
    )


# ─── Table initialisation ───

def init_cms_tables():
    conn = _db()
    cur = conn.cursor()

    cur.execute('''CREATE TABLE IF NOT EXISTS cms_pages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT NOT NULL UNIQUE,
        page_type TEXT NOT NULL DEFAULT 'landing',
        title TEXT NOT NULL,
        seo_title TEXT DEFAULT '',
        seo_description TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'draft',
        is_system INTEGER NOT NULL DEFAULT 0,
        created_by INTEGER,
        updated_by INTEGER,
        published_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS cms_page_sections(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        page_id INTEGER NOT NULL,
        section_key TEXT NOT NULL,
        section_type TEXT NOT NULL DEFAULT 'richtext',
        title TEXT DEFAULT '',
        eyebrow TEXT DEFAULT '',
        body_text TEXT DEFAULT '',
        cta_label TEXT DEFAULT '',
        cta_url TEXT DEFAULT '',
        image_url TEXT DEFAULT '',
        config TEXT DEFAULT '{}',
        sequence_order INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'draft',
        created_by INTEGER,
        updated_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(page_id, section_key),
        FOREIGN KEY(page_id) REFERENCES cms_pages(id) ON DELETE CASCADE
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS cms_media_library(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_type TEXT NOT NULL DEFAULT 'image',
        title TEXT DEFAULT '',
        alt_text TEXT DEFAULT '',
        credit TEXT DEFAULT '',
        original_filename TEXT NOT NULL,
        stored_filename TEXT NOT NULL,
        storage_key TEXT NOT NULL,
        mime_type TEXT NOT NULL,
        file_size_bytes INTEGER NOT NULL DEFAULT 0,
        checksum_sha256 TEXT DEFAULT '',
        public_url TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active',
        uploaded_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS cms_navigation_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        zone TEXT NOT NULL DEFAULT 'main',
        label TEXT NOT NULL,
        url TEXT DEFAULT '',
        page_id INTEGER,
        parent_id INTEGER,
        sequence_order INTEGER NOT NULL DEFAULT 0,
        is_visible INTEGER NOT NULL DEFAULT 1,
        target TEXT DEFAULT '_self',
        created_by INTEGER,
        updated_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(page_id) REFERENCES cms_pages(id) ON DELETE SET NULL,
        FOREIGN KEY(parent_id) REFERENCES cms_navigation_items(id) ON DELETE SET NULL
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS cms_site_settings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        setting_key TEXT NOT NULL UNIQUE,
        setting_value TEXT DEFAULT '',
        group_name TEXT DEFAULT 'general',
        label TEXT DEFAULT '',
        editable_type TEXT DEFAULT 'text',
        is_public INTEGER NOT NULL DEFAULT 0,
        updated_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS cms_revisions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_type TEXT NOT NULL,
        entity_id INTEGER NOT NULL,
        snapshot TEXT NOT NULL DEFAULT '{}',
        revision_note TEXT DEFAULT '',
        created_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')

    # Indices
    cur.execute('CREATE INDEX IF NOT EXISTS idx_cms_pages_slug ON cms_pages(slug)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_cms_pages_status ON cms_pages(status)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_cms_sections_page ON cms_page_sections(page_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_cms_media_status ON cms_media_library(status)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_cms_nav_zone ON cms_navigation_items(zone)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_cms_settings_key ON cms_site_settings(setting_key)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_cms_revisions_entity ON cms_revisions(entity_type, entity_id)')

    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════════════
#  PUBLIC ENDPOINTS (no auth required)
# ══════════════════════════════════════════════════════════════════

# ─── Public: site settings ───

@cms_router.get('/public/site-settings')
def public_site_settings():
    conn = _db()
    rows = conn.execute(
        'SELECT setting_key, setting_value, group_name, label, editable_type FROM cms_site_settings WHERE is_public=1 ORDER BY group_name, setting_key'
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        d = dict(r)
        d['setting_value'] = _parse_json_field(d['setting_value'])
        result[d['setting_key']] = d
    return {'settings': result}


# ─── Public: navigation ───

@cms_router.get('/public/navigation')
def public_navigation(zone: str = Query('main')):
    conn = _db()
    rows = conn.execute(
        '''SELECT id, zone, label, url, page_id, parent_id, sequence_order, target
           FROM cms_navigation_items
           WHERE zone=? AND is_visible=1
           ORDER BY sequence_order ASC, id ASC''',
        (zone,),
    ).fetchall()
    conn.close()
    return {'items': _rows_to_list(rows)}


# ─── Public: page by slug ───

@cms_router.get('/public/pages/{slug}')
def public_page_by_slug(slug: str):
    conn = _db()
    page = conn.execute(
        'SELECT * FROM cms_pages WHERE slug=? AND status=?', (slug, 'published')
    ).fetchone()
    if not page:
        conn.close()
        raise HTTPException(404, 'Page not found')
    page_dict = dict(page)

    sections = conn.execute(
        '''SELECT * FROM cms_page_sections
           WHERE page_id=? AND status=?
           ORDER BY sequence_order ASC, id ASC''',
        (page_dict['id'], 'published'),
    ).fetchall()
    conn.close()

    page_dict['sections'] = [_enrich_section_dict(dict(s)) for s in sections]
    return {'page': _enrich_page_dict(page_dict)}


# ─── Public: serve media file ───

@cms_router.get('/media/{media_id}/file')
def serve_media_file(media_id: int):
    conn = _db()
    media = conn.execute(
        'SELECT * FROM cms_media_library WHERE id=? AND status=?', (media_id, 'active')
    ).fetchone()
    conn.close()
    if not media:
        raise HTTPException(404, 'Media not found')

    stored = media['stored_filename']
    # Path traversal protection
    if '..' in stored or '/' in stored or '\\' in stored or '\0' in stored:
        raise HTTPException(400, 'Invalid media path')

    file_path = os.path.realpath(os.path.join(CMS_MEDIA_DIR, stored))
    media_root = os.path.realpath(CMS_MEDIA_DIR)
    if not file_path.startswith(media_root + os.sep) and file_path != media_root:
        raise HTTPException(400, 'Invalid media path')

    if not os.path.isfile(file_path):
        raise HTTPException(404, 'Media file not found on disk')

    mime = media['mime_type'] or 'application/octet-stream'
    headers = {
        'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; sandbox",
    }

    # SVG safety: serve as download to prevent XSS
    _, ext = os.path.splitext(stored.lower())
    if ext == '.svg' or mime == 'image/svg+xml':
        headers['Content-Disposition'] = f'attachment; filename="{_safe_filename(media["original_filename"])}"'
        return FileResponse(
            file_path,
            media_type='application/octet-stream',
            headers=headers,
        )

    return FileResponse(file_path, media_type=mime, headers=headers)


# ══════════════════════════════════════════════════════════════════
#  ADMIN ENDPOINTS (require admin/manager auth)
# ══════════════════════════════════════════════════════════════════

# ─── Admin: list pages ───

@cms_router.get('/admin/pages')
def admin_list_pages(
    status: Optional[str] = None,
    page_type: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user=Depends(_require_admin),
):
    conn = _db()
    conditions = []
    params: list = []

    if status:
        conditions.append('p.status=?')
        params.append(status)
    if page_type:
        conditions.append('p.page_type=?')
        params.append(page_type)
    if search:
        conditions.append('(p.title LIKE ? COLLATE NOCASE OR p.slug LIKE ? COLLATE NOCASE)')
        params.extend([f'%{search}%', f'%{search}%'])

    where = (' WHERE ' + ' AND '.join(conditions)) if conditions else ''

    total = conn.execute(f'SELECT COUNT(*) FROM cms_pages p{where}', params).fetchone()[0]

    rows = conn.execute(
        f'''SELECT p.*, u.name AS creator_name
            FROM cms_pages p
            LEFT JOIN users u ON u.id = p.created_by
            {where}
            ORDER BY p.updated_at DESC
            LIMIT ? OFFSET ?''',
        params + [limit, offset],
    ).fetchall()
    conn.close()

    return {'pages': _rows_to_list(rows), 'total': total, 'limit': limit, 'offset': offset}


# ─── Admin: create page ───

@cms_router.post('/admin/pages')
async def admin_create_page(request: Request, user=Depends(_require_admin)):
    body = await request.json()
    slug = (body.get('slug') or '').strip().lower()
    title = (body.get('title') or '').strip()

    if not slug:
        raise HTTPException(400, 'slug is required')
    if not title:
        raise HTTPException(400, 'title is required')

    # Slugs: only alphanumeric, hyphens, underscores, forward slashes
    if not re.match(r'^[a-z0-9][a-z0-9\-_/]*$', slug):
        raise HTTPException(400, 'slug must be lowercase alphanumeric with hyphens, underscores, or slashes')

    now = _utcnow()
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            '''INSERT INTO cms_pages(slug, page_type, title, seo_title, seo_description, status, is_system, created_by, updated_by, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
            (
                slug,
                body.get('page_type', 'landing'),
                title,
                body.get('seo_title', ''),
                body.get('seo_description', ''),
                body.get('status', 'draft'),
                int(body.get('is_system', 0)),
                user['id'],
                user['id'],
                now,
                now,
            ),
        )
        conn.commit()
        page_id = cur.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(409, f'A page with slug "{slug}" already exists')
    finally:
        conn.close()

    conn = _db()
    page = conn.execute('SELECT * FROM cms_pages WHERE id=?', (page_id,)).fetchone()
    conn.close()
    return {'page': dict(page)}


# ─── Admin: get page ───

@cms_router.get('/admin/pages/{page_id}')
def admin_get_page(page_id: int, user=Depends(_require_admin)):
    conn = _db()
    page = conn.execute('SELECT * FROM cms_pages WHERE id=?', (page_id,)).fetchone()
    if not page:
        conn.close()
        raise HTTPException(404, 'Page not found')
    page_dict = dict(page)

    sections = conn.execute(
        '''SELECT * FROM cms_page_sections
           WHERE page_id=?
           ORDER BY sequence_order ASC, id ASC''',
        (page_id,),
    ).fetchall()
    conn.close()

    page_dict['sections'] = [_enrich_section_dict(dict(s)) for s in sections]
    return {'page': _enrich_page_dict(page_dict)}


# ─── Admin: update page ───

@cms_router.patch('/admin/pages/{page_id}')
async def admin_update_page(page_id: int, request: Request, user=Depends(_require_admin)):
    conn = _db()
    page = conn.execute('SELECT * FROM cms_pages WHERE id=?', (page_id,)).fetchone()
    if not page:
        conn.close()
        raise HTTPException(404, 'Page not found')

    # Save revision
    _save_revision(conn, 'page', page_id, dict(page), 'pre-update', user['id'])

    body = await request.json()
    now = _utcnow()

    updatable = {
        'title', 'slug', 'page_type', 'seo_title', 'seo_description', 'status', 'is_system',
    }
    sets = ['updated_by=?', 'updated_at=?']
    params: list = [user['id'], now]

    for key in updatable:
        if key in body:
            val = body[key]
            if key == 'slug':
                val = (val or '').strip().lower()
                if not val:
                    conn.close()
                    raise HTTPException(400, 'slug cannot be empty')
                if not re.match(r'^[a-z0-9][a-z0-9\-_/]*$', val):
                    conn.close()
                    raise HTTPException(400, 'slug must be lowercase alphanumeric with hyphens, underscores, or slashes')
            if key == 'is_system':
                val = int(val)
            sets.append(f'{key}=?')
            params.append(val)

    params.append(page_id)
    try:
        conn.execute(f'UPDATE cms_pages SET {", ".join(sets)} WHERE id=?', params)
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(409, 'A page with that slug already exists')

    page = conn.execute('SELECT * FROM cms_pages WHERE id=?', (page_id,)).fetchone()
    conn.close()
    return {'page': dict(page)}


# ─── Admin: publish page ───

@cms_router.post('/admin/pages/{page_id}/publish')
def admin_publish_page(page_id: int, user=Depends(_require_admin)):
    conn = _db()
    page = conn.execute('SELECT * FROM cms_pages WHERE id=?', (page_id,)).fetchone()
    if not page:
        conn.close()
        raise HTTPException(404, 'Page not found')

    now = _utcnow()

    # Save revision
    _save_revision(conn, 'page', page_id, dict(page), 'pre-publish', user['id'])

    # Publish the page
    conn.execute(
        'UPDATE cms_pages SET status=?, published_at=COALESCE(published_at, ?), updated_by=?, updated_at=? WHERE id=?',
        ('published', now, user['id'], now, page_id),
    )

    # Publish all draft sections for this page
    conn.execute(
        'UPDATE cms_page_sections SET status=?, updated_by=?, updated_at=? WHERE page_id=? AND status=?',
        ('published', user['id'], now, page_id, 'draft'),
    )

    conn.commit()

    updated_page = conn.execute('SELECT * FROM cms_pages WHERE id=?', (page_id,)).fetchone()
    sections = conn.execute(
        'SELECT * FROM cms_page_sections WHERE page_id=? ORDER BY sequence_order ASC, id ASC',
        (page_id,),
    ).fetchall()
    conn.close()

    result = dict(updated_page)
    result['sections'] = [_enrich_section_dict(dict(s)) for s in sections]
    return {'page': result}


# ─── Admin: add section to page ───

@cms_router.post('/admin/pages/{page_id}/sections')
async def admin_add_section(page_id: int, request: Request, user=Depends(_require_admin)):
    conn = _db()
    page = conn.execute('SELECT id FROM cms_pages WHERE id=?', (page_id,)).fetchone()
    if not page:
        conn.close()
        raise HTTPException(404, 'Page not found')

    body = await request.json()
    section_key = (body.get('section_key') or '').strip()
    if not section_key:
        conn.close()
        raise HTTPException(400, 'section_key is required')

    # Validate URLs
    cta_url = _validate_url(body.get('cta_url', ''), 'cta_url')
    image_url = _validate_url(body.get('image_url', ''), 'image_url')

    config = body.get('config', {})
    if isinstance(config, dict):
        config = json.dumps(config)
    elif isinstance(config, str):
        # Validate it's valid JSON
        try:
            json.loads(config)
        except (json.JSONDecodeError, TypeError):
            conn.close()
            raise HTTPException(400, 'config must be valid JSON')

    now = _utcnow()
    try:
        cur = conn.cursor()
        cur.execute(
            '''INSERT INTO cms_page_sections(
                page_id, section_key, section_type, title, eyebrow, body_text,
                cta_label, cta_url, image_url, config, sequence_order, status,
                created_by, updated_by, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (
                page_id,
                section_key,
                body.get('section_type', 'richtext'),
                body.get('title', ''),
                body.get('eyebrow', ''),
                body.get('body_text', ''),
                body.get('cta_label', ''),
                cta_url,
                image_url,
                config,
                int(body.get('sequence_order', 0)),
                body.get('status', 'draft'),
                user['id'],
                user['id'],
                now,
                now,
            ),
        )
        conn.commit()
        section_id = cur.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(409, f'Section key "{section_key}" already exists for this page')

    section = conn.execute('SELECT * FROM cms_page_sections WHERE id=?', (section_id,)).fetchone()
    conn.close()
    return {'section': _enrich_section_dict(dict(section))}


# ─── Admin: update section ───

@cms_router.patch('/admin/sections/{section_id}')
async def admin_update_section(section_id: int, request: Request, user=Depends(_require_admin)):
    conn = _db()
    section = conn.execute('SELECT * FROM cms_page_sections WHERE id=?', (section_id,)).fetchone()
    if not section:
        conn.close()
        raise HTTPException(404, 'Section not found')

    # Save revision before update
    _save_revision(conn, 'section', section_id, dict(section), 'pre-update', user['id'])

    body = await request.json()
    now = _utcnow()

    updatable = {
        'section_key', 'section_type', 'title', 'eyebrow', 'body_text',
        'cta_label', 'cta_url', 'image_url', 'config', 'sequence_order', 'status',
    }
    sets = ['updated_by=?', 'updated_at=?']
    params: list = [user['id'], now]

    for key in updatable:
        if key in body:
            val = body[key]
            if key == 'cta_url':
                val = _validate_url(val, 'cta_url')
            elif key == 'image_url':
                val = _validate_url(val, 'image_url')
            elif key == 'config':
                if isinstance(val, dict):
                    val = json.dumps(val)
                elif isinstance(val, str):
                    try:
                        json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        conn.close()
                        raise HTTPException(400, 'config must be valid JSON')
            elif key == 'sequence_order':
                val = int(val)
            sets.append(f'{key}=?')
            params.append(val)

    params.append(section_id)
    try:
        conn.execute(f'UPDATE cms_page_sections SET {", ".join(sets)} WHERE id=?', params)
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(409, 'Section key conflict for this page')

    section = conn.execute('SELECT * FROM cms_page_sections WHERE id=?', (section_id,)).fetchone()
    conn.close()
    return {'section': _enrich_section_dict(dict(section))}


# ─── Admin: archive (soft-delete) section ───

@cms_router.delete('/admin/sections/{section_id}')
def admin_archive_section(section_id: int, user=Depends(_require_admin)):
    conn = _db()
    section = conn.execute('SELECT * FROM cms_page_sections WHERE id=?', (section_id,)).fetchone()
    if not section:
        conn.close()
        raise HTTPException(404, 'Section not found')

    # Save revision before archiving
    _save_revision(conn, 'section', section_id, dict(section), 'pre-archive', user['id'])

    now = _utcnow()
    conn.execute(
        'UPDATE cms_page_sections SET status=?, updated_by=?, updated_at=? WHERE id=?',
        ('archived', user['id'], now, section_id),
    )
    conn.commit()
    conn.close()
    return {'status': 'archived', 'section_id': section_id}


# ─── Admin: list media ───

@cms_router.get('/admin/media')
def admin_list_media(
    asset_type: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user=Depends(_require_admin),
):
    conn = _db()
    conditions = ['m.status=?']
    params: list = ['active']

    if asset_type:
        conditions.append('m.asset_type=?')
        params.append(asset_type)
    if search:
        conditions.append('(m.title LIKE ? COLLATE NOCASE OR m.original_filename LIKE ? COLLATE NOCASE)')
        params.extend([f'%{search}%', f'%{search}%'])

    where = ' WHERE ' + ' AND '.join(conditions)

    total = conn.execute(f'SELECT COUNT(*) FROM cms_media_library m{where}', params).fetchone()[0]

    rows = conn.execute(
        f'''SELECT m.*, u.name AS uploader_name
            FROM cms_media_library m
            LEFT JOIN users u ON u.id = m.uploaded_by
            {where}
            ORDER BY m.created_at DESC
            LIMIT ? OFFSET ?''',
        params + [limit, offset],
    ).fetchall()
    conn.close()

    return {'media': _rows_to_list(rows), 'total': total, 'limit': limit, 'offset': offset}


# ─── Admin: upload media ───

@cms_router.post('/admin/media')
async def admin_upload_media(
    file: UploadFile = File(...),
    title: str = Form(''),
    alt_text: str = Form(''),
    credit: str = Form(''),
    asset_type: str = Form('image'),
    user=Depends(_require_admin),
):
    if not file.filename:
        raise HTTPException(400, 'No file provided')

    ext = _validate_extension(file.filename)

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(413, f'File exceeds {MAX_UPLOAD_SIZE // (1024 * 1024)}MB limit')

    # Compute checksum
    checksum = hashlib.sha256(content).hexdigest()

    # Build stored filename
    unique_id = secrets.token_hex(16)
    safe_original = _safe_filename(file.filename)
    stored_filename = f'{unique_id}{ext}'
    storage_key = f'media/{stored_filename}'

    file_path = os.path.join(CMS_MEDIA_DIR, stored_filename)
    with open(file_path, 'wb') as f:
        f.write(content)

    # Detect MIME type
    mime = file.content_type or mimetypes.guess_type(file.filename)[0] or 'application/octet-stream'

    # Build public URL
    public_url = f'/api/cms/media/{0}/file'  # placeholder, updated after insert

    now = _utcnow()
    conn = _db()
    cur = conn.cursor()
    cur.execute(
        '''INSERT INTO cms_media_library(
            asset_type, title, alt_text, credit, original_filename, stored_filename,
            storage_key, mime_type, file_size_bytes, checksum_sha256, public_url,
            status, uploaded_by, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (
            asset_type,
            title or os.path.splitext(safe_original)[0],
            alt_text,
            credit,
            file.filename,
            stored_filename,
            storage_key,
            mime,
            len(content),
            checksum,
            '',  # will update below
            'active',
            user['id'],
            now,
            now,
        ),
    )
    conn.commit()
    media_id = cur.lastrowid

    # Update public_url with actual ID
    public_url = f'/api/cms/media/{media_id}/file'
    conn.execute('UPDATE cms_media_library SET public_url=? WHERE id=?', (public_url, media_id))
    conn.commit()

    media = conn.execute('SELECT * FROM cms_media_library WHERE id=?', (media_id,)).fetchone()
    conn.close()

    return {'media': dict(media)}


# ─── Admin: update media metadata ───

@cms_router.patch('/admin/media/{media_id}')
async def admin_update_media(media_id: int, request: Request, user=Depends(_require_admin)):
    conn = _db()
    media = conn.execute('SELECT * FROM cms_media_library WHERE id=?', (media_id,)).fetchone()
    if not media:
        conn.close()
        raise HTTPException(404, 'Media not found')

    body = await request.json()
    now = _utcnow()

    updatable = {'title', 'alt_text', 'credit', 'asset_type', 'status'}
    sets = ['updated_at=?']
    params: list = [now]

    for key in updatable:
        if key in body:
            sets.append(f'{key}=?')
            params.append(body[key])

    params.append(media_id)
    conn.execute(f'UPDATE cms_media_library SET {", ".join(sets)} WHERE id=?', params)
    conn.commit()

    media = conn.execute('SELECT * FROM cms_media_library WHERE id=?', (media_id,)).fetchone()
    conn.close()
    return {'media': dict(media)}


# ─── Admin: list navigation items ───

@cms_router.get('/admin/navigation')
def admin_list_navigation(
    zone: Optional[str] = None,
    user=Depends(_require_admin),
):
    conn = _db()
    if zone:
        rows = conn.execute(
            '''SELECT n.*, p.title AS page_title, p.slug AS page_slug
               FROM cms_navigation_items n
               LEFT JOIN cms_pages p ON p.id = n.page_id
               WHERE n.zone=?
               ORDER BY n.sequence_order ASC, n.id ASC''',
            (zone,),
        ).fetchall()
    else:
        rows = conn.execute(
            '''SELECT n.*, p.title AS page_title, p.slug AS page_slug
               FROM cms_navigation_items n
               LEFT JOIN cms_pages p ON p.id = n.page_id
               ORDER BY n.zone ASC, n.sequence_order ASC, n.id ASC'''
        ).fetchall()
    conn.close()
    return {'items': _rows_to_list(rows)}


# ─── Admin: add navigation item ───

@cms_router.post('/admin/navigation')
async def admin_add_navigation(request: Request, user=Depends(_require_admin)):
    body = await request.json()
    label = (body.get('label') or '').strip()
    if not label:
        raise HTTPException(400, 'label is required')

    url = _validate_url(body.get('url', ''), 'url')

    now = _utcnow()
    conn = _db()
    cur = conn.cursor()
    cur.execute(
        '''INSERT INTO cms_navigation_items(
            zone, label, url, page_id, parent_id, sequence_order,
            is_visible, target, created_by, updated_by, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
        (
            body.get('zone', 'main'),
            label,
            url,
            body.get('page_id'),
            body.get('parent_id'),
            int(body.get('sequence_order', 0)),
            int(body.get('is_visible', 1)),
            body.get('target', '_self'),
            user['id'],
            user['id'],
            now,
            now,
        ),
    )
    conn.commit()
    nav_id = cur.lastrowid

    item = conn.execute('SELECT * FROM cms_navigation_items WHERE id=?', (nav_id,)).fetchone()
    conn.close()
    return {'item': dict(item)}


# ─── Admin: update navigation item ───

@cms_router.patch('/admin/navigation/{nav_id}')
async def admin_update_navigation(nav_id: int, request: Request, user=Depends(_require_admin)):
    conn = _db()
    item = conn.execute('SELECT * FROM cms_navigation_items WHERE id=?', (nav_id,)).fetchone()
    if not item:
        conn.close()
        raise HTTPException(404, 'Navigation item not found')

    body = await request.json()
    now = _utcnow()

    updatable = {
        'zone', 'label', 'url', 'page_id', 'parent_id',
        'sequence_order', 'is_visible', 'target',
    }
    sets = ['updated_by=?', 'updated_at=?']
    params: list = [user['id'], now]

    for key in updatable:
        if key in body:
            val = body[key]
            if key == 'url':
                val = _validate_url(val, 'url')
            elif key == 'sequence_order':
                val = int(val)
            elif key == 'is_visible':
                val = int(val)
            sets.append(f'{key}=?')
            params.append(val)

    params.append(nav_id)
    conn.execute(f'UPDATE cms_navigation_items SET {", ".join(sets)} WHERE id=?', params)
    conn.commit()

    item = conn.execute('SELECT * FROM cms_navigation_items WHERE id=?', (nav_id,)).fetchone()
    conn.close()
    return {'item': dict(item)}


# ─── Admin: delete navigation item ───

@cms_router.delete('/admin/navigation/{nav_id}')
def admin_delete_navigation(nav_id: int, user=Depends(_require_admin)):
    conn = _db()
    item = conn.execute('SELECT id FROM cms_navigation_items WHERE id=?', (nav_id,)).fetchone()
    if not item:
        conn.close()
        raise HTTPException(404, 'Navigation item not found')

    conn.execute('DELETE FROM cms_navigation_items WHERE id=?', (nav_id,))
    conn.commit()
    conn.close()
    return {'status': 'deleted', 'nav_id': nav_id}


# ─── Admin: list site settings ───

@cms_router.get('/admin/site-settings')
def admin_list_settings(
    group_name: Optional[str] = None,
    user=Depends(_require_admin),
):
    conn = _db()
    if group_name:
        rows = conn.execute(
            'SELECT * FROM cms_site_settings WHERE group_name=? ORDER BY group_name, setting_key',
            (group_name,),
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM cms_site_settings ORDER BY group_name, setting_key'
        ).fetchall()
    conn.close()
    return {'settings': [_enrich_setting_dict(dict(r)) for r in rows]}


# ─── Admin: update site settings (bulk or single) ───

@cms_router.patch('/admin/site-settings')
async def admin_update_settings(request: Request, user=Depends(_require_admin)):
    body = await request.json()
    settings = body.get('settings', {})

    if not isinstance(settings, dict) or not settings:
        raise HTTPException(400, 'settings must be a non-empty object mapping setting_key to value')

    now = _utcnow()
    conn = _db()
    updated = []

    for key, value in settings.items():
        key = str(key).strip()
        if not key:
            continue

        # Serialize complex values to JSON string
        if isinstance(value, (dict, list)):
            stored_value = json.dumps(value)
        else:
            stored_value = str(value)

        existing = conn.execute('SELECT id FROM cms_site_settings WHERE setting_key=?', (key,)).fetchone()
        if existing:
            conn.execute(
                'UPDATE cms_site_settings SET setting_value=?, updated_by=?, updated_at=? WHERE setting_key=?',
                (stored_value, user['id'], now, key),
            )
        else:
            conn.execute(
                '''INSERT INTO cms_site_settings(setting_key, setting_value, group_name, label, editable_type, is_public, updated_by, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?)''',
                (key, stored_value, body.get('group_name', 'general'), key, 'text', 0, user['id'], now, now),
            )
        updated.append(key)

    conn.commit()
    conn.close()
    return {'updated': updated, 'count': len(updated)}


# ─── Admin: create/upsert a single site setting with full metadata ───

@cms_router.post('/admin/site-settings')
async def admin_create_setting(request: Request, user=Depends(_require_admin)):
    body = await request.json()
    key = (body.get('setting_key') or '').strip()
    if not key:
        raise HTTPException(400, 'setting_key is required')

    value = body.get('setting_value', '')
    if isinstance(value, (dict, list)):
        stored_value = json.dumps(value)
    else:
        stored_value = str(value)

    now = _utcnow()
    conn = _db()
    try:
        conn.execute(
            '''INSERT INTO cms_site_settings(setting_key, setting_value, group_name, label, editable_type, is_public, updated_by, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(setting_key) DO UPDATE SET
               setting_value=excluded.setting_value,
               group_name=excluded.group_name,
               label=excluded.label,
               editable_type=excluded.editable_type,
               is_public=excluded.is_public,
               updated_by=excluded.updated_by,
               updated_at=excluded.updated_at''',
            (
                key,
                stored_value,
                body.get('group_name', 'general'),
                body.get('label', key),
                body.get('editable_type', 'text'),
                int(body.get('is_public', 0)),
                user['id'],
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    conn = _db()
    setting = conn.execute('SELECT * FROM cms_site_settings WHERE setting_key=?', (key,)).fetchone()
    conn.close()
    return {'setting': _enrich_setting_dict(dict(setting))}
