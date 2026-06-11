
import os, json, hmac, hashlib, base64, time, sqlite3, re
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Depends, Header, Request, Query
from pydantic import BaseModel, Field

# ─── Paths & config ───

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, '..'))
DB_PATH = os.getenv('DATABASE_FILE', os.path.join(ROOT_DIR, 'data', 'finnish_paradigm.sqlite'))

VALID_PROVIDERS = {'vimeo', 'youtube', 'heygen', 'external'}
VALID_STATUSES = {'draft', 'published', 'archived'}
VALID_COMPLETION_STATUSES = {'not_started', 'in_progress', 'completed'}

# ─── Router ───

videos_router = APIRouter(prefix='/api/videos', tags=['Videos'])

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
    user = conn.execute('SELECT id,name,email,role,organisation,active FROM users WHERE id=?', (payload['sub'],)).fetchone()
    conn.close()
    if not user or not user['active']:
        raise HTTPException(401, 'User not found or inactive')
    return dict(user)


def _require_admin(user=Depends(_current_user)):
    if user['role'] not in ('admin', 'manager'):
        raise HTTPException(403, 'Admin or manager role required')
    return user


# ─── Helpers ───


def _validate_url(url: Optional[str], field_name: str) -> Optional[str]:
    """Validate that a URL uses http or https scheme. Returns None for empty/None."""
    if not url or not url.strip():
        return None
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise HTTPException(400, f'{field_name} must use http or https scheme')
    return url


def _check_enrollment(conn, user_id: int, course_id: str, user_role: str):
    """Check enrollment or admin/manager bypass."""
    if user_role in ('admin', 'manager'):
        return True
    enrollment = conn.execute(
        'SELECT id FROM enrollments WHERE user_id=? AND course_id=?',
        (user_id, course_id)
    ).fetchone()
    if not enrollment:
        raise HTTPException(403, 'You must be enrolled in this course to access video content')
    return True


def _check_module_course(conn, module_id: str, course_id: str):
    """Verify module belongs to course via lms_modules table."""
    row = conn.execute(
        'SELECT module_id FROM lms_modules WHERE module_id=? AND course_id=?',
        (module_id, course_id)
    ).fetchone()
    if not row:
        raise HTTPException(400, f'Module {module_id} does not belong to course {course_id}')
    return True


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ─── Tables ───


def init_video_tables():
    conn = _db()
    cur = conn.cursor()

    cur.execute('''CREATE TABLE IF NOT EXISTS cms_video_entries(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id TEXT NOT NULL,
        module_id TEXT NOT NULL,
        video_code TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        provider TEXT DEFAULT 'external',
        video_url TEXT NOT NULL,
        embed_url TEXT,
        caption_url TEXT,
        thumbnail_url TEXT,
        transcript TEXT,
        duration_seconds INTEGER,
        sequence_order INTEGER DEFAULT 1,
        completion_required INTEGER DEFAULT 1,
        minimum_watch_percentage INTEGER DEFAULT 90,
        status TEXT DEFAULT 'published',
        created_by INTEGER,
        created_at TEXT,
        updated_at TEXT,
        UNIQUE(module_id, video_code)
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS learner_video_progress(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        course_id TEXT NOT NULL,
        module_id TEXT NOT NULL,
        video_id INTEGER NOT NULL,
        watched_seconds INTEGER DEFAULT 0,
        duration_seconds INTEGER,
        watch_percentage INTEGER DEFAULT 0,
        completion_status TEXT DEFAULT 'not_started',
        completed_at TEXT,
        last_position_seconds INTEGER DEFAULT 0,
        created_at TEXT,
        updated_at TEXT,
        UNIQUE(user_id, video_id)
    )''')

    cur.execute('CREATE INDEX IF NOT EXISTS idx_cms_video_course ON cms_video_entries(course_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_cms_video_module ON cms_video_entries(module_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_lvp_user ON learner_video_progress(user_id, course_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_lvp_video ON learner_video_progress(video_id)')

    conn.commit()
    conn.close()


# ─── Pydantic models ───


class VideoCreateIn(BaseModel):
    course_id: str
    module_id: str
    video_code: str
    title: str = Field(min_length=1, max_length=500)
    description: Optional[str] = None
    provider: Optional[str] = 'external'
    video_url: str
    embed_url: Optional[str] = None
    caption_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    transcript: Optional[str] = None
    duration_seconds: Optional[int] = None
    sequence_order: Optional[int] = 1
    completion_required: Optional[int] = 1
    minimum_watch_percentage: Optional[int] = 90
    status: Optional[str] = 'published'


class VideoUpdateIn(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    provider: Optional[str] = None
    video_url: Optional[str] = None
    embed_url: Optional[str] = None
    caption_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    transcript: Optional[str] = None
    duration_seconds: Optional[int] = None
    sequence_order: Optional[int] = None
    completion_required: Optional[int] = None
    minimum_watch_percentage: Optional[int] = None
    status: Optional[str] = None


class VideoProgressIn(BaseModel):
    watched_seconds: int = Field(ge=0)
    last_position_seconds: int = Field(ge=0)
    duration_seconds: Optional[int] = Field(default=None, ge=1)


# ─── Learner Endpoints ───


@videos_router.get('/learner/courses/{course_id}/modules/{module_id}')
def learner_module_videos(course_id: str, module_id: str, user=Depends(_current_user)):
    conn = _db()
    try:
        _check_enrollment(conn, user['id'], course_id, user['role'])

        videos = conn.execute('''
            SELECT id, course_id, module_id, video_code, title, description,
                   provider, video_url, embed_url, caption_url, thumbnail_url,
                   duration_seconds, sequence_order, completion_required,
                   minimum_watch_percentage, status
            FROM cms_video_entries
            WHERE course_id=? AND module_id=? AND status='published'
            ORDER BY sequence_order, id
        ''', (course_id, module_id)).fetchall()

        result = []
        for v in videos:
            vd = dict(v)
            progress = conn.execute('''
                SELECT watched_seconds, duration_seconds, watch_percentage,
                       completion_status, completed_at, last_position_seconds
                FROM learner_video_progress
                WHERE user_id=? AND video_id=?
            ''', (user['id'], v['id'])).fetchone()
            vd['progress'] = dict(progress) if progress else {
                'watched_seconds': 0, 'duration_seconds': None,
                'watch_percentage': 0, 'completion_status': 'not_started',
                'completed_at': None, 'last_position_seconds': 0
            }
            result.append(vd)

        return {'videos': result, 'total': len(result)}
    finally:
        conn.close()


@videos_router.get('/learner/course/{course_id}/progress')
def learner_course_video_progress(course_id: str, user=Depends(_current_user)):
    conn = _db()
    try:
        _check_enrollment(conn, user['id'], course_id, user['role'])

        videos = conn.execute('''
            SELECT id, module_id, video_code, title, completion_required,
                   minimum_watch_percentage
            FROM cms_video_entries
            WHERE course_id=? AND status='published'
            ORDER BY module_id, sequence_order, id
        ''', (course_id,)).fetchall()

        total_videos = len(videos)
        completed_videos = 0
        required_videos = 0
        completed_required = 0
        module_progress = {}

        for v in videos:
            mid = v['module_id']
            if mid not in module_progress:
                module_progress[mid] = {'total': 0, 'completed': 0, 'required': 0, 'completed_required': 0}

            module_progress[mid]['total'] += 1
            is_required = bool(v['completion_required'])
            if is_required:
                required_videos += 1
                module_progress[mid]['required'] += 1

            prog = conn.execute('''
                SELECT completion_status FROM learner_video_progress
                WHERE user_id=? AND video_id=?
            ''', (user['id'], v['id'])).fetchone()

            if prog and prog['completion_status'] == 'completed':
                completed_videos += 1
                module_progress[mid]['completed'] += 1
                if is_required:
                    completed_required += 1
                    module_progress[mid]['completed_required'] += 1

        overall_percentage = int((completed_videos / total_videos * 100) if total_videos > 0 else 0)

        return {
            'course_id': course_id,
            'total_videos': total_videos,
            'completed_videos': completed_videos,
            'required_videos': required_videos,
            'completed_required': completed_required,
            'overall_percentage': overall_percentage,
            'all_required_complete': completed_required >= required_videos,
            'module_progress': module_progress
        }
    finally:
        conn.close()


@videos_router.post('/learner/{video_id}/progress')
def report_video_progress(video_id: int, payload: VideoProgressIn, user=Depends(_current_user)):
    conn = _db()
    try:
        video = conn.execute(
            'SELECT id, course_id, module_id, minimum_watch_percentage, duration_seconds FROM cms_video_entries WHERE id=? AND status=?',
            (video_id, 'published')
        ).fetchone()
        if not video:
            raise HTTPException(404, 'Video not found')

        _check_enrollment(conn, user['id'], video['course_id'], user['role'])

        # Use video's stored duration, or the one reported by the player, or the payload
        duration = payload.duration_seconds or video['duration_seconds']
        watched = payload.watched_seconds

        # Derive watch_percentage server-side
        if duration and duration > 0:
            watch_percentage = min(100, int(watched / duration * 100))
        else:
            watch_percentage = 0

        # Determine completion
        min_pct = video['minimum_watch_percentage'] or 90
        now = _now_iso()
        auto_complete = watch_percentage >= min_pct

        existing = conn.execute(
            'SELECT id, completion_status, completed_at FROM learner_video_progress WHERE user_id=? AND video_id=?',
            (user['id'], video_id)
        ).fetchone()

        if existing:
            # Don't downgrade from completed
            if existing['completion_status'] == 'completed':
                completion_status = 'completed'
                completed_at = existing['completed_at']
            elif auto_complete:
                completion_status = 'completed'
                completed_at = now
            else:
                completion_status = 'in_progress'
                completed_at = None

            conn.execute('''
                UPDATE learner_video_progress SET
                    watched_seconds=MAX(watched_seconds, ?),
                    duration_seconds=?,
                    watch_percentage=MAX(watch_percentage, ?),
                    completion_status=?,
                    completed_at=COALESCE(?, completed_at),
                    last_position_seconds=?,
                    updated_at=?
                WHERE user_id=? AND video_id=?
            ''', (
                watched, duration, watch_percentage,
                completion_status, completed_at,
                payload.last_position_seconds, now,
                user['id'], video_id
            ))
        else:
            completion_status = 'completed' if auto_complete else ('in_progress' if watched > 0 else 'not_started')
            completed_at = now if auto_complete else None

            conn.execute('''
                INSERT INTO learner_video_progress(
                    user_id, course_id, module_id, video_id,
                    watched_seconds, duration_seconds, watch_percentage,
                    completion_status, completed_at, last_position_seconds,
                    created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                user['id'], video['course_id'], video['module_id'], video_id,
                watched, duration, watch_percentage,
                completion_status, completed_at, payload.last_position_seconds,
                now, now
            ))

        conn.commit()

        return {
            'video_id': video_id,
            'watched_seconds': watched,
            'watch_percentage': watch_percentage,
            'completion_status': completion_status,
            'completed_at': completed_at,
            'last_position_seconds': payload.last_position_seconds
        }
    finally:
        conn.close()


@videos_router.patch('/learner/{video_id}/complete')
def force_complete_video(video_id: int, user=Depends(_current_user)):
    conn = _db()
    try:
        video = conn.execute(
            'SELECT id, course_id, module_id FROM cms_video_entries WHERE id=? AND status=?',
            (video_id, 'published')
        ).fetchone()
        if not video:
            raise HTTPException(404, 'Video not found')

        _check_enrollment(conn, user['id'], video['course_id'], user['role'])

        now = _now_iso()
        existing = conn.execute(
            'SELECT id FROM learner_video_progress WHERE user_id=? AND video_id=?',
            (user['id'], video_id)
        ).fetchone()

        if existing:
            conn.execute('''
                UPDATE learner_video_progress SET
                    watch_percentage=100,
                    completion_status='completed',
                    completed_at=COALESCE(completed_at, ?),
                    updated_at=?
                WHERE user_id=? AND video_id=?
            ''', (now, now, user['id'], video_id))
        else:
            conn.execute('''
                INSERT INTO learner_video_progress(
                    user_id, course_id, module_id, video_id,
                    watched_seconds, duration_seconds, watch_percentage,
                    completion_status, completed_at, last_position_seconds,
                    created_at, updated_at
                ) VALUES(?,?,?,?,0,NULL,100,'completed',?,0,?,?)
            ''', (
                user['id'], video['course_id'], video['module_id'], video_id,
                now, now, now
            ))

        conn.commit()
        return {'video_id': video_id, 'completion_status': 'completed', 'completed_at': now}
    finally:
        conn.close()


# ─── Admin Endpoints ───


@videos_router.get('/admin')
def admin_list_videos(
    course_id: Optional[str] = Query(None),
    module_id: Optional[str] = Query(None),
    user=Depends(_require_admin)
):
    conn = _db()
    try:
        query = '''
            SELECT v.*, u.name AS creator_name
            FROM cms_video_entries v
            LEFT JOIN users u ON u.id = v.created_by
            WHERE 1=1
        '''
        params: list = []

        if course_id:
            query += ' AND v.course_id=?'
            params.append(course_id)
        if module_id:
            query += ' AND v.module_id=?'
            params.append(module_id)

        query += ' ORDER BY v.course_id, v.module_id, v.sequence_order, v.id'
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@videos_router.post('/admin')
def admin_create_video(payload: VideoCreateIn, user=Depends(_require_admin)):
    # Validate provider
    provider = (payload.provider or 'external').lower()
    if provider not in VALID_PROVIDERS:
        raise HTTPException(400, f'Invalid provider. Must be one of: {", ".join(sorted(VALID_PROVIDERS))}')

    # Validate status
    status = (payload.status or 'published').lower()
    if status not in VALID_STATUSES:
        raise HTTPException(400, f'Invalid status. Must be one of: {", ".join(sorted(VALID_STATUSES))}')

    # Validate URLs
    video_url = _validate_url(payload.video_url, 'video_url')
    if not video_url:
        raise HTTPException(400, 'video_url is required and must be a valid http/https URL')
    embed_url = _validate_url(payload.embed_url, 'embed_url')
    caption_url = _validate_url(payload.caption_url, 'caption_url')
    thumbnail_url = _validate_url(payload.thumbnail_url, 'thumbnail_url')

    conn = _db()
    try:
        # Verify module belongs to course
        _check_module_course(conn, payload.module_id, payload.course_id)

        now = _now_iso()
        cur = conn.cursor()
        cur.execute('''INSERT INTO cms_video_entries(
            course_id, module_id, video_code, title, description,
            provider, video_url, embed_url, caption_url, thumbnail_url,
            transcript, duration_seconds, sequence_order, completion_required,
            minimum_watch_percentage, status, created_by, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
            payload.course_id, payload.module_id, payload.video_code,
            payload.title, payload.description,
            provider, video_url, embed_url, caption_url, thumbnail_url,
            payload.transcript, payload.duration_seconds,
            payload.sequence_order or 1, payload.completion_required if payload.completion_required is not None else 1,
            payload.minimum_watch_percentage if payload.minimum_watch_percentage is not None else 90,
            status, user['id'], now, now
        ))
        conn.commit()
        video_id = cur.lastrowid

        return {
            'id': video_id,
            'status': 'created',
            'course_id': payload.course_id,
            'module_id': payload.module_id,
            'video_code': payload.video_code,
            'title': payload.title
        }
    except sqlite3.IntegrityError:
        raise HTTPException(409, f'Video with code "{payload.video_code}" already exists for module "{payload.module_id}"')
    finally:
        conn.close()


@videos_router.patch('/admin/{video_id}')
def admin_update_video(video_id: int, payload: VideoUpdateIn, user=Depends(_require_admin)):
    conn = _db()
    try:
        existing = conn.execute('SELECT * FROM cms_video_entries WHERE id=?', (video_id,)).fetchone()
        if not existing:
            raise HTTPException(404, 'Video not found')

        updates = []
        params = []

        if payload.title is not None:
            if not payload.title.strip():
                raise HTTPException(400, 'Title cannot be empty')
            updates.append('title=?')
            params.append(payload.title.strip())

        if payload.description is not None:
            updates.append('description=?')
            params.append(payload.description)

        if payload.provider is not None:
            p = payload.provider.lower()
            if p not in VALID_PROVIDERS:
                raise HTTPException(400, f'Invalid provider. Must be one of: {", ".join(sorted(VALID_PROVIDERS))}')
            updates.append('provider=?')
            params.append(p)

        if payload.video_url is not None:
            url = _validate_url(payload.video_url, 'video_url')
            if not url:
                raise HTTPException(400, 'video_url must be a valid http/https URL')
            updates.append('video_url=?')
            params.append(url)

        if payload.embed_url is not None:
            updates.append('embed_url=?')
            params.append(_validate_url(payload.embed_url, 'embed_url'))

        if payload.caption_url is not None:
            updates.append('caption_url=?')
            params.append(_validate_url(payload.caption_url, 'caption_url'))

        if payload.thumbnail_url is not None:
            updates.append('thumbnail_url=?')
            params.append(_validate_url(payload.thumbnail_url, 'thumbnail_url'))

        if payload.transcript is not None:
            updates.append('transcript=?')
            params.append(payload.transcript)

        if payload.duration_seconds is not None:
            updates.append('duration_seconds=?')
            params.append(payload.duration_seconds)

        if payload.sequence_order is not None:
            updates.append('sequence_order=?')
            params.append(payload.sequence_order)

        if payload.completion_required is not None:
            updates.append('completion_required=?')
            params.append(payload.completion_required)

        if payload.minimum_watch_percentage is not None:
            updates.append('minimum_watch_percentage=?')
            params.append(payload.minimum_watch_percentage)

        if payload.status is not None:
            s = payload.status.lower()
            if s not in VALID_STATUSES:
                raise HTTPException(400, f'Invalid status. Must be one of: {", ".join(sorted(VALID_STATUSES))}')
            updates.append('status=?')
            params.append(s)

        if not updates:
            raise HTTPException(400, 'No fields to update')

        updates.append('updated_at=?')
        params.append(_now_iso())
        params.append(video_id)

        conn.execute(f'UPDATE cms_video_entries SET {",".join(updates)} WHERE id=?', params)
        conn.commit()

        updated = conn.execute('SELECT * FROM cms_video_entries WHERE id=?', (video_id,)).fetchone()
        return dict(updated)
    finally:
        conn.close()


@videos_router.delete('/admin/{video_id}')
def admin_delete_video(video_id: int, user=Depends(_require_admin)):
    conn = _db()
    try:
        existing = conn.execute('SELECT id, title FROM cms_video_entries WHERE id=?', (video_id,)).fetchone()
        if not existing:
            raise HTTPException(404, 'Video not found')

        now = _now_iso()
        conn.execute(
            "UPDATE cms_video_entries SET status='archived', updated_at=? WHERE id=?",
            (now, video_id)
        )
        conn.commit()

        return {'status': 'archived', 'video_id': video_id, 'title': existing['title']}
    finally:
        conn.close()


@videos_router.get('/admin/reports/progress')
def admin_video_progress_report(
    course_id: Optional[str] = Query(None),
    module_id: Optional[str] = Query(None),
    user=Depends(_require_admin)
):
    conn = _db()
    try:
        query = '''
            SELECT lvp.*, u.name AS learner_name, u.email AS learner_email,
                   v.title AS video_title, v.video_code, v.module_id, v.course_id
            FROM learner_video_progress lvp
            JOIN users u ON u.id = lvp.user_id
            JOIN cms_video_entries v ON v.id = lvp.video_id
            WHERE 1=1
        '''
        params: list = []

        if course_id:
            query += ' AND lvp.course_id=?'
            params.append(course_id)
        if module_id:
            query += ' AND lvp.module_id=?'
            params.append(module_id)

        query += ' ORDER BY lvp.updated_at DESC LIMIT 500'
        rows = conn.execute(query, params).fetchall()

        return {'progress': [dict(r) for r in rows], 'total': len(rows)}
    finally:
        conn.close()
