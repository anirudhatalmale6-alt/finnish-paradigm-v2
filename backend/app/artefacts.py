
import os, json, hmac, hashlib, base64, time, secrets, sqlite3, mimetypes
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

ARTEFACT_STORAGE = os.path.join(os.path.dirname(STATIC_DIR), 'artefact-storage')
os.makedirs(ARTEFACT_STORAGE, exist_ok=True)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

ALLOWED_EXTENSIONS = {
    '.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.csv', '.txt',
    '.jpg', '.jpeg', '.png', '.webp',
    '.mp4', '.mov',
    '.zip',
}

BLOCKED_EXTENSIONS = {
    '.exe', '.bat', '.cmd', '.com', '.scr', '.msi', '.vbs', '.js', '.jar',
    '.sh', '.php', '.py', '.rb', '.pl', '.ps1', '.dll',
}

artefacts_router = APIRouter(prefix='/api/artefacts', tags=['Artefacts'])

# ─── DB + Auth (self-contained, same logic as main.py) ───

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

# ─── Artefact tables ───

def init_artefact_tables():
    conn = _db()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS course_evidence_requirements(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id TEXT NOT NULL,
        module_id TEXT,
        requirement_code TEXT NOT NULL,
        title TEXT NOT NULL,
        instructions TEXT,
        evidence_type TEXT DEFAULT 'portfolio_evidence',
        required_for_certificate INTEGER DEFAULT 1,
        sequence_order INTEGER DEFAULT 1,
        max_file_size_mb INTEGER DEFAULT 100,
        allowed_file_extensions TEXT,
        status TEXT DEFAULT 'active',
        created_by INTEGER,
        created_at TEXT,
        updated_at TEXT,
        UNIQUE(course_id, requirement_code)
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS learner_artefacts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        course_id TEXT NOT NULL,
        module_id TEXT,
        requirement_id INTEGER,
        title TEXT NOT NULL,
        description TEXT,
        evidence_type TEXT DEFAULT 'portfolio_evidence',
        storage_key TEXT NOT NULL,
        original_filename TEXT NOT NULL,
        stored_filename TEXT NOT NULL,
        mime_type TEXT,
        file_size_bytes INTEGER DEFAULT 0,
        checksum_sha256 TEXT,
        status TEXT DEFAULT 'submitted',
        reviewer_id INTEGER,
        reviewer_feedback TEXT,
        reviewed_at TEXT,
        submitted_at TEXT,
        created_at TEXT,
        updated_at TEXT
    )''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_learner_artefacts_user ON learner_artefacts(user_id, course_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_learner_artefacts_status ON learner_artefacts(status)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_evidence_req_course ON course_evidence_requirements(course_id)')
    conn.commit()
    conn.close()

# ─── Helpers ───

def _check_enrollment(user_id: int, course_id: str, conn) -> bool:
    enrollment = conn.execute(
        'SELECT id FROM enrollments WHERE user_id=? AND course_id=?',
        (user_id, course_id)
    ).fetchone()
    return bool(enrollment)

def _validate_file(filename: str, file_size: int, max_size_mb: int = 100):
    if not filename:
        raise HTTPException(400, 'Filename is required')

    _, ext = os.path.splitext(filename.lower())

    if ext in BLOCKED_EXTENSIONS:
        raise HTTPException(400, f'File type {ext} is not allowed for security reasons')

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f'File type {ext} is not in the allowed list: {", ".join(sorted(ALLOWED_EXTENSIONS))}')

    max_bytes = max_size_mb * 1024 * 1024
    if file_size > max_bytes:
        raise HTTPException(413, f'File exceeds the {max_size_mb}MB size limit')

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _safe_filename(filename: str) -> str:
    name, ext = os.path.splitext(filename)
    safe_name = ''.join(c if c.isalnum() or c in '._-' else '_' for c in name)
    return f'{safe_name}{ext.lower()}'

def _store_file(user_id: int, course_id: str, filename: str, content: bytes) -> tuple:
    """Store file and return (storage_key, stored_filename, full_path)."""
    unique_prefix = secrets.token_hex(8)
    safe_name = _safe_filename(filename)
    stored_filename = f'{unique_prefix}_{safe_name}'
    storage_key = f'{user_id}/{course_id}/{stored_filename}'

    dir_path = os.path.join(ARTEFACT_STORAGE, str(user_id), course_id)
    os.makedirs(dir_path, exist_ok=True)

    full_path = os.path.join(dir_path, stored_filename)
    with open(full_path, 'wb') as f:
        f.write(content)

    return storage_key, stored_filename, full_path

def _resolve_file_path(storage_key: str) -> str:
    """Resolve a storage key to an absolute file path, with path traversal protection."""
    if '\0' in storage_key or '..' in storage_key:
        raise HTTPException(400, 'Invalid storage key')
    full_path = os.path.realpath(os.path.join(ARTEFACT_STORAGE, storage_key))
    root = os.path.realpath(ARTEFACT_STORAGE)
    if not full_path.startswith(root + os.sep) and full_path != root:
        raise HTTPException(400, 'Invalid storage key')
    if not os.path.isfile(full_path):
        raise HTTPException(404, 'Artefact file not found on disk')
    return full_path

# ─── Learner endpoints ───

@artefacts_router.get('/requirements')
def get_evidence_requirements(
    course_id: str = Query(...),
    module_id: Optional[str] = Query(None),
    user=Depends(_current_user)
):
    conn = _db()
    is_admin = user['role'] in ('admin', 'manager')
    if not is_admin and not _check_enrollment(user['id'], course_id, conn):
        conn.close()
        raise HTTPException(403, 'You must be enrolled in this course')

    if module_id:
        rows = conn.execute(
            'SELECT * FROM course_evidence_requirements WHERE course_id=? AND module_id=? AND status=? ORDER BY sequence_order',
            (course_id, module_id, 'active')
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM course_evidence_requirements WHERE course_id=? AND status=? ORDER BY sequence_order',
            (course_id, 'active')
        ).fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        if d.get('allowed_file_extensions'):
            try:
                d['allowed_file_extensions'] = json.loads(d['allowed_file_extensions'])
            except Exception:
                pass
        result.append(d)
    return result

@artefacts_router.get('/learner')
def list_own_artefacts(
    course_id: Optional[str] = Query(None),
    module_id: Optional[str] = Query(None),
    user=Depends(_current_user)
):
    conn = _db()
    query = 'SELECT * FROM learner_artefacts WHERE user_id=?'
    params: list = [user['id']]

    if course_id:
        query += ' AND course_id=?'
        params.append(course_id)
    if module_id:
        query += ' AND module_id=?'
        params.append(module_id)

    query += ' ORDER BY id DESC'
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@artefacts_router.post('/learner/upload')
async def upload_artefact(
    file: UploadFile = File(...),
    course_id: str = Form(...),
    title: str = Form(...),
    module_id: Optional[str] = Form(None),
    requirement_id: Optional[int] = Form(None),
    description: Optional[str] = Form(None),
    evidence_type: Optional[str] = Form('portfolio_evidence'),
    user=Depends(_current_user)
):
    conn = _db()
    is_admin = user['role'] in ('admin', 'manager')
    if not is_admin and not _check_enrollment(user['id'], course_id, conn):
        conn.close()
        raise HTTPException(403, 'You must be enrolled in this course to upload evidence')

    # Determine max file size from requirement if linked
    max_size_mb = 100
    if requirement_id:
        req = conn.execute(
            'SELECT * FROM course_evidence_requirements WHERE id=? AND course_id=?',
            (requirement_id, course_id)
        ).fetchone()
        if not req:
            conn.close()
            raise HTTPException(404, 'Evidence requirement not found for this course')
        if req['max_file_size_mb']:
            max_size_mb = req['max_file_size_mb']

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Validate file
    _validate_file(file.filename or 'unknown', file_size, max_size_mb)

    # Compute checksum
    checksum = _sha256(content)

    # Determine MIME type
    mime_type = file.content_type or mimetypes.guess_type(file.filename or '')[0] or 'application/octet-stream'

    # Store file
    storage_key, stored_filename, _ = _store_file(user['id'], course_id, file.filename or 'upload', content)

    # Insert record
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()
    cur.execute('''INSERT INTO learner_artefacts(
        user_id, course_id, module_id, requirement_id, title, description,
        evidence_type, storage_key, original_filename, stored_filename,
        mime_type, file_size_bytes, checksum_sha256, status,
        submitted_at, created_at, updated_at
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
        user['id'], course_id, module_id, requirement_id, title, description,
        evidence_type or 'portfolio_evidence', storage_key, file.filename or 'upload',
        stored_filename, mime_type, file_size, checksum, 'submitted',
        now, now, now
    ))
    conn.commit()
    artefact_id = cur.lastrowid
    conn.close()

    return {
        'id': artefact_id,
        'status': 'submitted',
        'storage_key': storage_key,
        'original_filename': file.filename,
        'file_size_bytes': file_size,
        'checksum_sha256': checksum,
        'mime_type': mime_type,
    }

@artefacts_router.get('/learner/{artefact_id}/download')
def download_own_artefact(artefact_id: int, user=Depends(_current_user)):
    conn = _db()
    row = conn.execute('SELECT * FROM learner_artefacts WHERE id=? AND user_id=?', (artefact_id, user['id'])).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, 'Artefact not found or does not belong to you')

    full_path = _resolve_file_path(row['storage_key'])
    content_type = row['mime_type'] or 'application/octet-stream'
    return FileResponse(full_path, media_type=content_type, filename=row['original_filename'])

@artefacts_router.delete('/learner/{artefact_id}')
def withdraw_artefact(artefact_id: int, user=Depends(_current_user)):
    conn = _db()
    row = conn.execute('SELECT * FROM learner_artefacts WHERE id=? AND user_id=?', (artefact_id, user['id'])).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, 'Artefact not found or does not belong to you')

    if row['status'] in ('approved', 'under_review'):
        conn.close()
        raise HTTPException(400, f'Cannot withdraw an artefact with status "{row["status"]}". Only submitted artefacts can be withdrawn.')

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        'UPDATE learner_artefacts SET status=?, updated_at=? WHERE id=?',
        ('withdrawn', now, artefact_id)
    )
    conn.commit()
    conn.close()

    return {'status': 'withdrawn', 'artefact_id': artefact_id}

# ─── Admin endpoints ───

@artefacts_router.get('/admin')
def admin_list_artefacts(
    course_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    user=Depends(_require_admin)
):
    conn = _db()
    query = '''SELECT la.*, u.name AS learner_name, u.email AS learner_email
               FROM learner_artefacts la
               LEFT JOIN users u ON u.id = la.user_id'''
    conditions = []
    params: list = []

    if course_id:
        conditions.append('la.course_id=?')
        params.append(course_id)
    if status:
        conditions.append('la.status=?')
        params.append(status)

    if conditions:
        query += ' WHERE ' + ' AND '.join(conditions)

    query += ' ORDER BY la.id DESC'
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@artefacts_router.get('/admin/{artefact_id}/download')
def admin_download_artefact(artefact_id: int, user=Depends(_require_admin)):
    conn = _db()
    row = conn.execute('SELECT * FROM learner_artefacts WHERE id=?', (artefact_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, 'Artefact not found')

    full_path = _resolve_file_path(row['storage_key'])
    content_type = row['mime_type'] or 'application/octet-stream'
    return FileResponse(full_path, media_type=content_type, filename=row['original_filename'])

@artefacts_router.patch('/admin/{artefact_id}/review')
def review_artefact(
    artefact_id: int,
    status: str = Form(...),
    reviewer_feedback: Optional[str] = Form(None),
    user=Depends(_require_admin)
):
    valid_statuses = {'under_review', 'approved', 'resubmission_requested', 'rejected'}
    if status not in valid_statuses:
        raise HTTPException(400, f'Invalid review status. Must be one of: {", ".join(sorted(valid_statuses))}')

    conn = _db()
    row = conn.execute('SELECT * FROM learner_artefacts WHERE id=?', (artefact_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, 'Artefact not found')

    now = datetime.now(timezone.utc).isoformat()
    conn.execute('''UPDATE learner_artefacts SET
        status=?, reviewer_id=?, reviewer_feedback=?, reviewed_at=?, updated_at=?
        WHERE id=?''', (
        status, user['id'], reviewer_feedback, now, now, artefact_id
    ))
    conn.commit()
    conn.close()

    return {
        'artefact_id': artefact_id,
        'status': status,
        'reviewer_id': user['id'],
        'reviewed_at': now,
    }

@artefacts_router.post('/admin/requirements')
def create_or_upsert_requirement(
    course_id: str = Form(...),
    requirement_code: str = Form(...),
    title: str = Form(...),
    module_id: Optional[str] = Form(None),
    instructions: Optional[str] = Form(None),
    evidence_type: Optional[str] = Form('portfolio_evidence'),
    required_for_certificate: Optional[int] = Form(1),
    sequence_order: Optional[int] = Form(1),
    max_file_size_mb: Optional[int] = Form(100),
    allowed_file_extensions: Optional[str] = Form(None),
    status: Optional[str] = Form('active'),
    user=Depends(_require_admin)
):
    now = datetime.now(timezone.utc).isoformat()

    # Validate allowed_file_extensions if provided (should be a JSON array string)
    if allowed_file_extensions:
        try:
            exts = json.loads(allowed_file_extensions)
            if not isinstance(exts, list):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(400, 'allowed_file_extensions must be a JSON array string, e.g. [".pdf",".docx"]')

    conn = _db()
    cur = conn.cursor()
    cur.execute('''INSERT INTO course_evidence_requirements(
        course_id, module_id, requirement_code, title, instructions,
        evidence_type, required_for_certificate, sequence_order,
        max_file_size_mb, allowed_file_extensions, status,
        created_by, created_at, updated_at
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(course_id, requirement_code) DO UPDATE SET
        module_id=excluded.module_id,
        title=excluded.title,
        instructions=excluded.instructions,
        evidence_type=excluded.evidence_type,
        required_for_certificate=excluded.required_for_certificate,
        sequence_order=excluded.sequence_order,
        max_file_size_mb=excluded.max_file_size_mb,
        allowed_file_extensions=excluded.allowed_file_extensions,
        status=excluded.status,
        updated_at=excluded.updated_at
    ''', (
        course_id, module_id, requirement_code, title, instructions,
        evidence_type or 'portfolio_evidence', required_for_certificate, sequence_order,
        max_file_size_mb, allowed_file_extensions, status or 'active',
        user['id'], now, now
    ))
    conn.commit()
    req_id = cur.lastrowid
    # If upsert updated, lastrowid is 0; fetch actual id
    if req_id == 0:
        row = conn.execute(
            'SELECT id FROM course_evidence_requirements WHERE course_id=? AND requirement_code=?',
            (course_id, requirement_code)
        ).fetchone()
        req_id = row['id'] if row else 0
    conn.close()

    return {
        'id': req_id,
        'course_id': course_id,
        'requirement_code': requirement_code,
        'title': title,
        'status': 'saved',
    }
