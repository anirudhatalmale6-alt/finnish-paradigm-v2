
import os, json, hmac, hashlib, base64, time, secrets, sqlite3, zipfile, mimetypes
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from xml.etree import ElementTree
from fastapi import APIRouter, HTTPException, Depends, Header, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, '..'))
DB_PATH = os.getenv('DATABASE_FILE', os.path.join(ROOT_DIR, 'data', 'finnish_paradigm.sqlite'))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
def _get_jwt_secret():
    import backend.app.main as _main
    return _main.JWT_SECRET

SCORM_STORAGE = os.path.join(os.path.dirname(STATIC_DIR), 'scorm-storage')
SCORM_ZIPS_DIR = os.path.join(SCORM_STORAGE, 'zips')
SCORM_EXTRACT_DIR = os.path.join(SCORM_STORAGE, 'extracted')
os.makedirs(SCORM_ZIPS_DIR, exist_ok=True)
os.makedirs(SCORM_EXTRACT_DIR, exist_ok=True)

LAUNCH_TOKEN_TTL = 4 * 3600
MAX_ZIP_SIZE = 750 * 1024 * 1024
MAX_SUSPEND_DATA = 64 * 1024
MAX_CMI_JSON = 256 * 1024

VALID_LESSON_STATUS = {
    'not attempted', 'passed', 'completed', 'failed', 'browsed', 'incomplete'
}

scorm_router = APIRouter(prefix='/api/scorm', tags=['SCORM'])

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

def _optional_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.lower().startswith('bearer '):
        return None
    try:
        payload = _read_token(authorization.split(' ', 1)[1])
        conn = _db()
        user = conn.execute('SELECT id,name,email,role,organisation,active FROM users WHERE id=?', (payload['sub'],)).fetchone()
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

# ─── SCORM tables ───

def init_scorm_tables():
    conn = _db()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS scorm_packages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        package_name TEXT NOT NULL,
        original_filename TEXT NOT NULL,
        scorm_version TEXT NOT NULL DEFAULT '1.2',
        zip_path TEXT NOT NULL,
        extracted_path TEXT NOT NULL,
        launch_file TEXT NOT NULL,
        manifest_title TEXT,
        manifest_identifier TEXT,
        package_version TEXT NOT NULL DEFAULT '1.0',
        uploaded_by INTEGER,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS scorm_module_assignments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        module_id TEXT NOT NULL,
        scorm_package_id INTEGER NOT NULL,
        assigned_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(module_id)
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS scorm_attempts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT UNIQUE NOT NULL,
        user_id INTEGER NOT NULL,
        course_id TEXT NOT NULL,
        module_id TEXT NOT NULL,
        scorm_package_id INTEGER NOT NULL,
        attempt_number INTEGER NOT NULL DEFAULT 1,
        lesson_status TEXT NOT NULL DEFAULT 'not attempted',
        lesson_location TEXT DEFAULT '',
        suspend_data TEXT DEFAULT '',
        score_raw REAL,
        score_min REAL DEFAULT 0,
        score_max REAL DEFAULT 100,
        session_time TEXT DEFAULT '00:00:00',
        total_time_seconds INTEGER NOT NULL DEFAULT 0,
        cmi_json TEXT NOT NULL DEFAULT '{}',
        started_at TEXT NOT NULL,
        last_commit_at TEXT,
        completed_at TEXT,
        finished_at TEXT,
        UNIQUE(user_id, module_id, attempt_number)
    )''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_scorm_attempts_session ON scorm_attempts(session_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_scorm_attempts_user ON scorm_attempts(user_id, course_id)')
    conn.commit()
    conn.close()

# ─── Launch tokens ───

def _launch_secret():
    return _get_jwt_secret() + ':scorm-launch'

def sign_launch_token(session_id: str, user_id: int, package_id: int) -> str:
    payload = {
        'sid': session_id, 'sub': user_id, 'pkg': package_id,
        'exp': int(time.time()) + LAUNCH_TOKEN_TTL,
    }
    body = _b64url(json.dumps(payload, separators=(',', ':')).encode())
    sig = _b64url(hmac.new(_launch_secret().encode(), body.encode(), hashlib.sha256).digest())
    return f'{body}.{sig}'

def verify_launch_token(token: str) -> Dict[str, Any]:
    try:
        secret = _launch_secret()
        body, sig = token.split('.', 1)
        expected = _b64url(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            raise ValueError('bad sig')
        payload = json.loads(_b64url_decode(body))
        if payload.get('exp', 0) < time.time():
            raise ValueError('expired')
        return payload
    except Exception:
        raise HTTPException(401, 'Invalid or expired SCORM launch token')

# ─── SCORM manifest parsing ───

def parse_scorm_manifest(extracted_path: str) -> Dict[str, str]:
    manifest_path = os.path.join(extracted_path, 'imsmanifest.xml')
    if not os.path.exists(manifest_path):
        raise HTTPException(400, 'imsmanifest.xml not found in ZIP root. Ensure you zip the contents, not the folder.')
    tree = ElementTree.parse(manifest_path)
    root = tree.getroot()
    ns = root.tag.split('}')[0] + '}' if '}' in root.tag else ''
    identifier = root.attrib.get('identifier', '')
    title_el = root.find(f'.//{ns}organization/{ns}title')
    title = title_el.text if title_el is not None else ''
    resource = root.find(f'.//{ns}resource')
    if resource is None:
        raise HTTPException(400, 'No resource found in imsmanifest.xml')
    launch_file = resource.attrib.get('href', 'index.html')
    schema_el = root.find(f'.//{ns}metadata/{ns}schemaversion')
    version = '1.2'
    if schema_el is not None and schema_el.text:
        version = schema_el.text.strip()
    return {
        'identifier': identifier, 'title': title,
        'launch_file': launch_file, 'version': version,
    }

# ─── SCORM time helpers ───

def scorm_time_to_seconds(t: str) -> int:
    try:
        parts = t.split(':')
        h, m = int(parts[0]), int(parts[1])
        s = float(parts[2]) if len(parts) > 2 else 0.0
        return int(h * 3600 + m * 60 + s)
    except Exception:
        return 0

def seconds_to_scorm_time(total: int) -> str:
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f'{h:04d}:{m:02d}:{s:02d}'

def is_module_complete(lesson_status: str, score_raw, rule: str = 'completed_or_passed', pass_score: int = 70) -> bool:
    if rule == 'completed':
        return lesson_status == 'completed'
    elif rule == 'passed':
        return lesson_status == 'passed'
    elif rule == 'score_threshold':
        return score_raw is not None and score_raw >= pass_score
    return lesson_status in ('completed', 'passed')

# ─── Admin: upload SCORM package ───

@scorm_router.post('/admin/upload')
async def upload_scorm_package(
    package: UploadFile = File(...),
    package_name: str = Form(''),
    package_version: str = Form('1.0'),
    user=Depends(_require_admin)
):
    if not package.filename or not package.filename.lower().endswith('.zip'):
        raise HTTPException(400, 'Only SCORM ZIP files are allowed')

    upload_id = secrets.token_hex(12)
    safe_name = ''.join(c if c.isalnum() or c in '._-' else '_' for c in package.filename)
    zip_filename = f'{upload_id}-{safe_name}'
    zip_path = os.path.join(SCORM_ZIPS_DIR, zip_filename)
    extract_path = os.path.join(SCORM_EXTRACT_DIR, upload_id)

    content = await package.read()
    if len(content) > MAX_ZIP_SIZE:
        raise HTTPException(413, f'ZIP exceeds {MAX_ZIP_SIZE // (1024*1024)}MB limit')

    with open(zip_path, 'wb') as f:
        f.write(content)

    try:
        os.makedirs(extract_path, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for info in zf.infolist():
                if info.filename.startswith('/') or '..' in info.filename:
                    raise HTTPException(400, 'ZIP contains unsafe paths')
            zf.extractall(extract_path)
    except zipfile.BadZipFile:
        os.remove(zip_path)
        raise HTTPException(400, 'Invalid ZIP file')

    manifest = parse_scorm_manifest(extract_path)

    conn = _db()
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cur.execute('''INSERT INTO scorm_packages(
        package_name, original_filename, scorm_version, zip_path, extracted_path,
        launch_file, manifest_title, manifest_identifier, package_version,
        uploaded_by, is_active, created_at
    ) VALUES(?,?,?,?,?,?,?,?,?,?,1,?)''', (
        package_name or manifest['title'] or package.filename,
        package.filename, manifest['version'], zip_path, extract_path,
        manifest['launch_file'], manifest['title'], manifest['identifier'],
        package_version, user['id'], now,
    ))
    conn.commit()
    pkg_id = cur.lastrowid
    conn.close()

    return {
        'package_id': pkg_id,
        'package_name': package_name or manifest['title'] or package.filename,
        'launch_file': manifest['launch_file'],
        'scorm_version': manifest['version'],
        'status': 'uploaded',
    }

# ─── Admin: list packages ───

@scorm_router.get('/admin/packages')
def list_scorm_packages(user=Depends(_require_admin)):
    conn = _db()
    rows = conn.execute('''
        SELECT sp.*, u.name AS uploader_name,
               (SELECT GROUP_CONCAT(sma.module_id) FROM scorm_module_assignments sma WHERE sma.scorm_package_id = sp.id) AS assigned_modules
        FROM scorm_packages sp
        LEFT JOIN users u ON u.id = sp.uploaded_by
        WHERE sp.is_active = 1
        ORDER BY sp.id DESC
    ''').fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ─── Admin: assign package to module ───

@scorm_router.post('/admin/assign/{module_id}/{package_id}')
def assign_scorm_to_module(module_id: str, package_id: int, user=Depends(_require_admin)):
    conn = _db()
    cur = conn.cursor()
    pkg = cur.execute('SELECT id FROM scorm_packages WHERE id=? AND is_active=1', (package_id,)).fetchone()
    if not pkg:
        conn.close(); raise HTTPException(404, 'SCORM package not found')
    mod = cur.execute('SELECT module_id FROM lms_modules WHERE module_id=?', (module_id,)).fetchone()
    if not mod:
        conn.close(); raise HTTPException(404, 'Module not found')
    cur.execute('''INSERT INTO scorm_module_assignments(module_id, scorm_package_id, assigned_by, created_at)
        VALUES(?,?,?,?) ON CONFLICT(module_id) DO UPDATE SET
        scorm_package_id=excluded.scorm_package_id, assigned_by=excluded.assigned_by, created_at=excluded.created_at''',
        (module_id, package_id, user['id'], datetime.now(timezone.utc).isoformat()))
    conn.commit(); conn.close()
    return {'status': 'assigned', 'module_id': module_id, 'package_id': package_id}

# ─── Admin: SCORM progress report ───

@scorm_router.get('/admin/progress')
def scorm_progress_report(user=Depends(_require_admin)):
    conn = _db()
    rows = conn.execute('''
        SELECT u.name AS learner_name, u.email, sa.course_id, sa.module_id,
               sa.lesson_status, sa.score_raw, sa.total_time_seconds,
               sa.started_at, sa.last_commit_at, sa.completed_at, sa.attempt_number
        FROM scorm_attempts sa
        JOIN users u ON u.id = sa.user_id
        ORDER BY sa.last_commit_at DESC NULLS LAST
        LIMIT 500
    ''').fetchall()
    conn.close()
    return {'progress': [dict(r) for r in rows]}

# ─── Admin: delete package ───

@scorm_router.delete('/admin/packages/{package_id}')
def deactivate_scorm_package(package_id: int, user=Depends(_require_admin)):
    conn = _db()
    conn.execute('UPDATE scorm_packages SET is_active=0 WHERE id=?', (package_id,))
    conn.execute('DELETE FROM scorm_module_assignments WHERE scorm_package_id=?', (package_id,))
    conn.commit(); conn.close()
    return {'status': 'deactivated', 'package_id': package_id}

# ─── Learner: get module SCORM info ───

@scorm_router.get('/modules/{module_id}/info')
def scorm_module_info(module_id: str, user=Depends(_optional_user)):
    conn = _db()
    assignment = conn.execute('''
        SELECT sma.scorm_package_id, sp.package_name, sp.scorm_version
        FROM scorm_module_assignments sma
        JOIN scorm_packages sp ON sp.id = sma.scorm_package_id AND sp.is_active=1
        WHERE sma.module_id=?
    ''', (module_id,)).fetchone()
    if not assignment:
        conn.close(); return {'has_scorm': False}
    result = {'has_scorm': True, 'package_name': assignment['package_name'], 'scorm_version': assignment['scorm_version']}
    if user:
        latest = conn.execute('''
            SELECT lesson_status, score_raw, total_time_seconds, completed_at
            FROM scorm_attempts WHERE user_id=? AND module_id=?
            ORDER BY attempt_number DESC LIMIT 1
        ''', (user['id'], module_id)).fetchone()
        if latest:
            result['progress'] = dict(latest)
    conn.close()
    return result

# ─── Learner: create or resume SCORM session ───

@scorm_router.post('/modules/{module_id}/sessions')
def create_scorm_session(module_id: str, user=Depends(_current_user)):
    conn = _db()
    cur = conn.cursor()

    assignment = cur.execute('''
        SELECT sma.scorm_package_id, sp.id AS pkg_id
        FROM scorm_module_assignments sma
        JOIN scorm_packages sp ON sp.id = sma.scorm_package_id AND sp.is_active=1
        WHERE sma.module_id=?
    ''', (module_id,)).fetchone()
    if not assignment:
        conn.close(); raise HTTPException(404, 'No SCORM package assigned to this module')

    module = cur.execute('''
        SELECT m.module_id, m.course_id, m.title AS module_title, c.title AS course_title
        FROM lms_modules m JOIN lms_courses c ON c.course_id = m.course_id
        WHERE m.module_id=?
    ''', (module_id,)).fetchone()
    if not module:
        conn.close(); raise HTTPException(404, 'Module not found')

    enrollment = cur.execute('SELECT id FROM enrollments WHERE user_id=? AND course_id=?',
        (user['id'], module['course_id'])).fetchone()
    is_admin = user['role'] in ('admin', 'manager')
    if not enrollment and not is_admin:
        conn.close(); raise HTTPException(403, 'You must be enrolled in this course to launch SCORM content')

    latest = cur.execute('''
        SELECT * FROM scorm_attempts
        WHERE user_id=? AND module_id=?
        ORDER BY attempt_number DESC LIMIT 1
    ''', (user['id'], module_id)).fetchone()

    if latest and not latest['finished_at']:
        session_id = latest['session_id']
    else:
        attempt_number = (latest['attempt_number'] + 1) if latest else 1
        session_id = secrets.token_urlsafe(24)
        now = datetime.now(timezone.utc).isoformat()
        cur.execute('''INSERT INTO scorm_attempts(
            session_id, user_id, course_id, module_id, scorm_package_id,
            attempt_number, lesson_status, started_at
        ) VALUES(?,?,?,?,?,?,?,?)''', (
            session_id, user['id'], module['course_id'], module_id,
            assignment['pkg_id'], attempt_number, 'not attempted', now,
        ))
        conn.commit()

    launch_token = sign_launch_token(session_id, user['id'], assignment['pkg_id'])
    conn.close()

    return {
        'session_id': session_id,
        'player_url': f'/api/scorm/player/{session_id}?lt={launch_token}',
    }

# ─── SCORM Player HTML ───

def _esc(s: str) -> str:
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#39;')

@scorm_router.get('/player/{session_id}')
def scorm_player(session_id: str, lt: str = ''):
    if not lt:
        raise HTTPException(401, 'Launch token required')
    payload = verify_launch_token(lt)
    if payload['sid'] != session_id:
        raise HTTPException(403, 'Token does not match session')

    conn = _db()
    attempt = conn.execute('''
        SELECT sa.*, m.title AS module_title, c.title AS course_title,
               sp.id AS pkg_id, sp.launch_file
        FROM scorm_attempts sa
        JOIN lms_modules m ON m.module_id = sa.module_id
        JOIN lms_courses c ON c.course_id = sa.course_id
        JOIN scorm_packages sp ON sp.id = sa.scorm_package_id
        WHERE sa.session_id=?
    ''', (session_id,)).fetchone()
    conn.close()

    if not attempt:
        raise HTTPException(404, 'SCORM session not found')

    launch_url = f'/api/scorm/content/{attempt["pkg_id"]}/{attempt["launch_file"]}?lt={lt}'
    mt = _esc(attempt['module_title'])
    ct = _esc(attempt['course_title'])

    html = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{ct} — {mt} | FCEI</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{height:100%;font-family:'Hanken Grotesk',system-ui,sans-serif;background:#F7F5F0;color:#0E3A30}}
.player-bar{{
  height:56px;display:flex;align-items:center;justify-content:space-between;
  padding:0 20px;background:#0E3A30;color:#F7F5F0;
  border-bottom:3px solid #E8A13C;
}}
.player-bar .info .title{{font-weight:600;font-size:14px;letter-spacing:0.02em}}
.player-bar .info .breadcrumb{{font-size:12px;opacity:0.7;margin-top:2px}}
.player-bar .actions{{display:flex;gap:10px;align-items:center}}
.badge{{font-size:12px;padding:4px 10px;border-radius:20px;background:#11785C;color:#F7F5F0}}
.badge.done{{background:#E8A13C;color:#0E3A30;font-weight:600}}
.btn-finish{{
  border:none;padding:10px 18px;border-radius:8px;cursor:pointer;
  font-family:inherit;font-weight:600;font-size:13px;
  background:#E8A13C;color:#0E3A30;transition:background 0.2s;
}}
.btn-finish:hover{{background:#d4912e}}
.btn-back{{
  border:1px solid rgba(255,255,255,0.3);padding:8px 14px;border-radius:8px;cursor:pointer;
  font-family:inherit;font-weight:500;font-size:13px;
  background:transparent;color:#F7F5F0;transition:all 0.2s;
}}
.btn-back:hover{{background:rgba(255,255,255,0.1)}}
#scoFrame{{width:100%;height:calc(100vh - 59px);border:0;background:#fff}}
.overlay{{
  position:fixed;top:56px;left:0;right:0;bottom:0;
  background:#F7F5F0;display:flex;flex-direction:column;
  align-items:center;justify-content:center;z-index:100;
  transition:opacity 0.3s;
}}
.overlay.hide{{opacity:0;pointer-events:none}}
.spin{{width:40px;height:40px;border:3px solid #ddd;border-top-color:#11785C;border-radius:50%;animation:sp 0.8s linear infinite}}
@keyframes sp{{to{{transform:rotate(360deg)}}}}
.load-text{{margin-top:16px;font-size:14px;color:#0E3A30;opacity:0.7}}
</style>
</head>
<body>
<div class="player-bar">
  <div class="info">
    <div class="title">{mt}</div>
    <div class="breadcrumb">{ct}</div>
  </div>
  <div class="actions">
    <span class="badge" id="statusBadge">Loading...</span>
    <button class="btn-back" onclick="goBack()">&#8592; Back</button>
    <button class="btn-finish" onclick="finishAndExit()">Save &amp; Exit</button>
  </div>
</div>
<div class="overlay" id="lo">
  <div class="spin"></div>
  <div class="load-text">Loading SCORM module...</div>
</div>
<iframe id="scoFrame" src="{_esc(launch_url)}" allowfullscreen
  onload="document.getElementById('lo').classList.add('hide')"></iframe>

<script>
const SID={json.dumps(session_id)};
const LT={json.dumps(lt)};
let cmi={{}};
let init=false,lastErr='0',dirty=false,ct=null;

function se(c){{lastErr=String(c||'0')}}
function ok(){{se('0');return'true'}}
function fl(c){{se(c||'101');return'false'}}

function ub(){{
  const b=document.getElementById('statusBadge');
  const s=cmi['cmi.core.lesson_status']||'not attempted';
  b.textContent=s.charAt(0).toUpperCase()+s.slice(1);
  b.className=(s==='completed'||s==='passed')?'badge done':'badge';
}}

async function ls(){{
  const r=await fetch('/api/scorm/session/'+encodeURIComponent(SID)+'/state?lt='+encodeURIComponent(LT));
  if(!r.ok)throw new Error('Could not load SCORM state ('+r.status+')');
  const d=await r.json();cmi=d.cmi||{{}};ub();
}}

async function cs(fin){{
  const u='/api/scorm/session/'+encodeURIComponent(SID)+(fin?'/finish':'/commit')+'?lt='+encodeURIComponent(LT);
  const r=await fetch(u,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{cmi}})}});
  if(r.ok){{dirty=false;ub()}}return r.ok;
}}

function sac(){{if(ct)clearTimeout(ct);ct=setTimeout(()=>{{if(dirty)cs(false)}},30000)}}

function ro(k){{
  return['cmi.core.student_id','cmi.core.student_name','cmi.core.credit',
    'cmi.core.entry','cmi.core.total_time','cmi.core.lesson_mode',
    'cmi.core._children','cmi.core.score._children'].includes(k);
}}

window.API={{
  LMSInitialize:function(){{if(init)return ok();init=true;return ok()}},
  LMSFinish:function(){{if(!init)return fl('301');init=false;cs(true);return ok()}},
  LMSGetValue:function(k){{if(!init){{fl('301');return''}}se('0');return cmi[k]==null?'':String(cmi[k])}},
  LMSSetValue:function(k,v){{if(!init)return fl('301');if(!k)return fl('201');if(ro(k))return fl('403');cmi[k]=String(v==null?'':v);dirty=true;sac();ub();return ok()}},
  LMSCommit:function(){{if(!init)return fl('301');cs(false);return ok()}},
  LMSGetLastError:function(){{return lastErr}},
  LMSGetErrorString:function(c){{
    const e={{'0':'No error','101':'General exception','201':'Invalid argument error','301':'Not initialized','401':'Not implemented error','403':'Element is read only','404':'Element is write only','405':'Incorrect data type'}};
    return e[String(c)]||'Unknown error';
  }},
  LMSGetDiagnostic:function(c){{return'FCEI SCORM 1.2 runtime: '+(c||lastErr)}}
}};

function goBack(){{if(dirty)cs(false);window.history.back()}}
async function finishAndExit(){{await cs(true);if(window.opener)window.close();else window.history.back()}}

window.addEventListener('beforeunload',()=>{{
  try{{
    const b=new Blob([JSON.stringify({{cmi}})],{{type:'application/json'}});
    navigator.sendBeacon('/api/scorm/session/'+encodeURIComponent(SID)+'/commit?lt='+encodeURIComponent(LT),b);
  }}catch(e){{}}
}});

ls().catch(e=>{{
  document.getElementById('lo').innerHTML='<p style="padding:24px;color:#c0392b;font-size:16px">SCORM launch failed: '+e.message+'</p>';
}});
</script>
</body>
</html>'''
    return HTMLResponse(content=html)

# ─── SCORM content serving ───

@scorm_router.get('/content/{package_id}/{path:path}')
def serve_scorm_content(package_id: int, path: str, lt: str = ''):
    if not lt:
        raise HTTPException(401, 'Launch token required')
    payload = verify_launch_token(lt)
    if payload['pkg'] != package_id:
        raise HTTPException(403, 'Token not valid for this package')

    conn = _db()
    pkg = conn.execute('SELECT extracted_path FROM scorm_packages WHERE id=? AND is_active=1', (package_id,)).fetchone()
    conn.close()
    if not pkg:
        raise HTTPException(404, 'SCORM package not found')

    if '\0' in path or '..' in path:
        raise HTTPException(400, 'Invalid path')

    root = os.path.realpath(pkg['extracted_path'])
    file_path = os.path.realpath(os.path.join(root, path))
    if not file_path.startswith(root + os.sep) and file_path != root:
        raise HTTPException(400, 'Invalid path')
    if not os.path.isfile(file_path):
        raise HTTPException(404, 'File not found')

    content_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
    return FileResponse(file_path, media_type=content_type)

# ─── SCORM runtime: get state ───

@scorm_router.get('/session/{session_id}/state')
def get_scorm_state(session_id: str, lt: str = ''):
    if not lt:
        raise HTTPException(401, 'Launch token required')
    payload = verify_launch_token(lt)
    if payload['sid'] != session_id:
        raise HTTPException(403, 'Token does not match session')

    conn = _db()
    attempt = conn.execute('SELECT * FROM scorm_attempts WHERE session_id=?', (session_id,)).fetchone()
    if not attempt:
        conn.close(); raise HTTPException(404, 'Session not found')
    if attempt['user_id'] != payload['sub']:
        conn.close(); raise HTTPException(403, 'Token does not own this session')

    user = conn.execute('SELECT name FROM users WHERE id=?', (attempt['user_id'],)).fetchone()
    conn.close()

    stored = {}
    try:
        stored = json.loads(attempt['cmi_json'] or '{}')
    except Exception:
        pass

    has_suspend = bool(attempt['suspend_data'] and str(attempt['suspend_data']).strip())
    status = attempt['lesson_status'] or 'not attempted'
    entry = ''
    if status == 'not attempted' and not has_suspend:
        entry = 'ab-initio'
    elif has_suspend and not attempt['finished_at']:
        entry = 'resume'

    cmi = {
        **stored,
        'cmi.core._children': 'student_id,student_name,lesson_location,credit,lesson_status,entry,score,total_time,lesson_mode,exit,session_time',
        'cmi.core.student_id': str(attempt['user_id']),
        'cmi.core.student_name': user['name'] if user else '',
        'cmi.core.lesson_location': attempt['lesson_location'] or '',
        'cmi.core.credit': 'credit',
        'cmi.core.lesson_status': status,
        'cmi.core.entry': entry,
        'cmi.core.score._children': 'raw,min,max',
        'cmi.core.score.raw': '' if attempt['score_raw'] is None else str(attempt['score_raw']),
        'cmi.core.score.min': str(attempt['score_min'] or 0),
        'cmi.core.score.max': str(attempt['score_max'] or 100),
        'cmi.core.total_time': seconds_to_scorm_time(attempt['total_time_seconds']),
        'cmi.core.lesson_mode': 'normal',
        'cmi.core.exit': '',
        'cmi.core.session_time': '00:00:00',
        'cmi.suspend_data': attempt['suspend_data'] or '',
        'cmi.launch_data': '',
        'cmi.comments': '',
        'cmi.comments_from_lms': '',
    }
    return {'cmi': cmi}

# ─── SCORM runtime: save CMI data ───

def _save_cmi(session_id: str, cmi_data: dict, finished: bool, expected_user_id: int):
    if not cmi_data or not isinstance(cmi_data, dict):
        cmi_data = {}

    suspend_data = str(cmi_data.get('cmi.suspend_data', ''))
    if len(suspend_data.encode('utf-8')) > MAX_SUSPEND_DATA:
        raise HTTPException(413, 'cmi.suspend_data exceeds maximum size')
    cmi_str = json.dumps(cmi_data, separators=(',', ':'))
    if len(cmi_str.encode('utf-8')) > MAX_CMI_JSON:
        raise HTTPException(413, 'SCORM CMI payload exceeds maximum size')

    conn = _db()
    cur = conn.cursor()
    attempt = cur.execute('SELECT * FROM scorm_attempts WHERE session_id=?', (session_id,)).fetchone()
    if not attempt:
        conn.close(); return None
    if attempt['user_id'] != expected_user_id:
        conn.close(); raise HTTPException(403, 'Session does not belong to authenticated learner')

    lesson_status = cmi_data.get('cmi.core.lesson_status', attempt['lesson_status'] or 'incomplete')
    if lesson_status not in VALID_LESSON_STATUS:
        lesson_status = 'incomplete'

    def to_num(v, fallback):
        if v == '' or v is None:
            return fallback
        try:
            n = float(v)
            return n if n == n else fallback
        except (ValueError, TypeError):
            return fallback

    score_raw = to_num(cmi_data.get('cmi.core.score.raw'), None)
    score_min = to_num(cmi_data.get('cmi.core.score.min'), 0)
    score_max = to_num(cmi_data.get('cmi.core.score.max'), 100)

    session_time = cmi_data.get('cmi.core.session_time', '00:00:00')
    added_seconds = scorm_time_to_seconds(session_time) if finished else 0

    complete = is_module_complete(lesson_status, score_raw)
    now = datetime.now(timezone.utc).isoformat()

    cur.execute('''UPDATE scorm_attempts SET
        lesson_status=?, lesson_location=?, suspend_data=?,
        score_raw=?, score_min=?, score_max=?,
        session_time=?, total_time_seconds=total_time_seconds+?,
        cmi_json=?, last_commit_at=?,
        completed_at=CASE WHEN completed_at IS NOT NULL THEN completed_at WHEN ? THEN ? ELSE NULL END,
        finished_at=CASE WHEN ? THEN COALESCE(finished_at, ?) ELSE finished_at END
    WHERE session_id=?''', (
        lesson_status, cmi_data.get('cmi.core.lesson_location', ''), suspend_data,
        score_raw, score_min, score_max,
        session_time, added_seconds,
        cmi_str, now,
        int(complete), now,
        int(finished), now,
        session_id,
    ))

    if complete:
        cur.execute('''INSERT INTO learner_progress(user_id, course_id, module_id, video_complete, assessment_complete, artifact_uploaded, reflection_submitted, module_complete, completed_at, created_at, updated_at)
            VALUES(?,?,?,1,1,1,1,1,?,?,?)
            ON CONFLICT(user_id, course_id, module_id) DO UPDATE SET
            module_complete=1, completed_at=COALESCE(learner_progress.completed_at, excluded.completed_at), updated_at=excluded.updated_at''',
            (attempt['user_id'], attempt['course_id'], attempt['module_id'], now, now, now))

    conn.commit(); conn.close()
    return {'ok': True, 'lesson_status': lesson_status, 'completed': complete}

@scorm_router.post('/session/{session_id}/commit')
async def commit_scorm(session_id: str, request: Request, lt: str = ''):
    if not lt:
        raise HTTPException(401, 'Launch token required')
    payload = verify_launch_token(lt)
    if payload['sid'] != session_id:
        raise HTTPException(403, 'Token does not match session')

    body = await request.body()
    try:
        data = json.loads(body) if body else {}
    except Exception:
        data = {}

    result = _save_cmi(session_id, data.get('cmi', {}), False, payload['sub'])
    if not result:
        raise HTTPException(404, 'SCORM session not found')
    return result

@scorm_router.post('/session/{session_id}/finish')
async def finish_scorm(session_id: str, request: Request, lt: str = ''):
    if not lt:
        raise HTTPException(401, 'Launch token required')
    payload = verify_launch_token(lt)
    if payload['sid'] != session_id:
        raise HTTPException(403, 'Token does not match session')

    body = await request.body()
    try:
        data = json.loads(body) if body else {}
    except Exception:
        data = {}

    result = _save_cmi(session_id, data.get('cmi', {}), True, payload['sub'])
    if not result:
        raise HTTPException(404, 'SCORM session not found')
    return result
