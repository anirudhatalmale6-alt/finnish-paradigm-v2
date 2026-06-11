
import io, os, json, secrets
from fastapi.testclient import TestClient
from backend.app.main import app

_run_id = secrets.token_hex(4)

client = TestClient(app)

_admin_token = None
_learner_token = None

def admin_headers():
    global _admin_token
    if not _admin_token:
        r = client.post('/api/auth/login', json={'email': os.getenv('ADMIN_EMAIL', 'admin@fcei.edu'), 'password': os.getenv('ADMIN_PASSWORD', 'ChangeMeNow!123')})
        assert r.status_code == 200
        _admin_token = r.json()['access_token']
    return {'Authorization': 'Bearer ' + _admin_token}

def learner_headers():
    global _learner_token
    if not _learner_token:
        email = 'cms_integ_learner@example.com'
        r = client.post('/api/auth/register', json={'name': 'CMS Learner', 'email': email, 'password': 'StrongPass123', 'role': 'teacher'})
        if r.status_code == 409:
            r = client.post('/api/auth/login', json={'email': email, 'password': 'StrongPass123'})
        assert r.status_code == 200
        _learner_token = r.json()['access_token']
    return {'Authorization': 'Bearer ' + _learner_token}

# ─── CMS Tables ───

def test_cms_tables_created():
    from backend.app.cms import _db
    conn = _db()
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'cms%'").fetchall()]
    conn.close()
    assert 'cms_pages' in tables
    assert 'cms_page_sections' in tables
    assert 'cms_media_library' in tables
    assert 'cms_navigation_items' in tables
    assert 'cms_site_settings' in tables
    assert 'cms_revisions' in tables

# ─── CMS Pages ───

def test_create_and_publish_page():
    h = admin_headers()
    slug = f'integ-test-{_run_id}'
    r = client.post('/api/cms/admin/pages', json={
        'title': 'Integration Test Page',
        'slug': slug,
        'page_type': 'marketing',
        'status': 'draft'
    }, headers=h)
    assert r.status_code == 200
    page = r.json()['page']
    assert page['slug'] == slug
    page_id = page['id']

    r = client.post(f'/api/cms/admin/pages/{page_id}/sections', json={
        'section_key': 'hero-main',
        'section_type': 'hero',
        'title': 'Welcome to FCEI',
        'body_text': 'Finnish Creative Education Institute',
        'cta_label': 'Explore',
        'cta_url': '/courses',
        'sequence_order': 1,
        'status': 'draft'
    }, headers=h)
    assert r.status_code == 200

    r = client.post(f'/api/cms/admin/pages/{page_id}/publish', headers=h)
    assert r.status_code == 200
    assert r.json()['page']['status'] == 'published'

def test_list_pages():
    h = admin_headers()
    r = client.get('/api/cms/admin/pages', headers=h)
    assert r.status_code == 200
    data = r.json()
    assert 'pages' in data
    assert len(data['pages']) >= 1

def test_public_page_with_sections():
    r = client.get(f'/api/cms/public/pages/integ-test-{_run_id}')
    assert r.status_code == 200
    data = r.json()
    assert 'page' in data
    assert data['page']['title'] == 'Integration Test Page'

def test_section_url_validation():
    h = admin_headers()
    pages = client.get('/api/cms/admin/pages', headers=h).json()['pages']
    page_id = pages[0]['id']
    r = client.post(f'/api/cms/admin/pages/{page_id}/sections', json={
        'section_key': 'xss-test',
        'section_type': 'cta',
        'title': 'XSS Test',
        'cta_url': 'javascript:alert(1)',
    }, headers=h)
    assert r.status_code == 400

# ─── CMS Site Settings ───

def test_site_settings():
    h = admin_headers()
    r = client.post('/api/cms/admin/site-settings', json={
        'setting_key': 'site_name',
        'setting_value': 'FCEI Platform',
        'group_name': 'general',
        'label': 'Site Name',
        'is_public': True
    }, headers=h)
    assert r.status_code == 200

    r = client.get('/api/cms/public/site-settings')
    assert r.status_code == 200
    settings = r.json()['settings']
    assert 'site_name' in settings

# ─── CMS Navigation ───

def test_navigation():
    h = admin_headers()
    r = client.post('/api/cms/admin/navigation', json={
        'zone': 'main',
        'label': 'Courses',
        'url': '/courses',
        'sequence_order': 1,
        'is_visible': True
    }, headers=h)
    assert r.status_code == 200

    r = client.get('/api/cms/public/navigation?zone=main')
    assert r.status_code == 200
    data = r.json()
    nav_key = 'items' if 'items' in data else 'navigation'
    assert len(data[nav_key]) >= 1

# ─── CMS Media ───

def test_upload_and_list_media():
    h = admin_headers()
    img_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
    r = client.post('/api/cms/admin/media',
        files={'file': ('test-image.png', io.BytesIO(img_data), 'image/png')},
        data={'title': 'Test Image', 'alt_text': 'A test image'},
        headers=h)
    assert r.status_code == 200
    media = r.json()['media']
    assert media['title'] == 'Test Image'

    r = client.get('/api/cms/admin/media', headers=h)
    assert r.status_code == 200
    assert len(r.json()['media']) >= 1

# ─── CMS Auth ───

def test_cms_requires_admin():
    r = client.get('/api/cms/admin/pages')
    assert r.status_code == 401
    h = learner_headers()
    r = client.get('/api/cms/admin/pages', headers=h)
    assert r.status_code == 403

# ─── Video Tables ───

def test_video_tables_created():
    from backend.app.videos_api import _db
    conn = _db()
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('cms_video_entries','learner_video_progress')").fetchall()]
    conn.close()
    assert 'cms_video_entries' in tables
    assert 'learner_video_progress' in tables

# ─── Video Admin ───

def test_create_and_list_videos():
    h = admin_headers()
    r = client.post('/api/videos/admin', json={
        'course_id': 'C1',
        'module_id': 'M1',
        'video_code': f'V-INTEG-{_run_id}',
        'title': 'Introduction to Finnish Pedagogy',
        'provider': 'vimeo',
        'video_url': 'https://vimeo.com/123456',
        'duration_seconds': 360,
        'sequence_order': 1,
        'status': 'published'
    }, headers=h)
    assert r.status_code == 200
    data = r.json()
    vc = f'V-INTEG-{_run_id}'
    assert data.get('video_code') == vc or (isinstance(data, dict) and 'video' in data and data['video']['video_code'] == vc)

    r = client.get('/api/videos/admin', headers=h)
    assert r.status_code == 200
    vids = r.json()
    if isinstance(vids, list):
        assert len(vids) >= 1
    else:
        assert len(vids.get('videos', vids)) >= 1

def test_video_url_validation():
    h = admin_headers()
    r = client.post('/api/videos/admin', json={
        'course_id': 'C1',
        'module_id': 'M1',
        'video_code': 'V-BAD-URL',
        'title': 'Bad URL Test',
        'video_url': 'javascript:alert(1)',
    }, headers=h)
    assert r.status_code == 400

# ─── Video Learner ───

def test_learner_video_progress():
    h = learner_headers()
    client.post('/api/enrollments', json={'course_id': 'C1'}, headers=h)
    from backend.app.videos_api import _db
    conn = _db()
    vid = conn.execute("SELECT id FROM cms_video_entries WHERE video_code=?", (f'V-INTEG-{_run_id}',)).fetchone()
    conn.close()
    if vid:
        r = client.post(f'/api/videos/learner/{vid["id"]}/progress', json={
            'watched_seconds': 180,
            'duration_seconds': 360,
            'last_position_seconds': 180
        }, headers=h)
        assert r.status_code == 200
        data = r.json()
        prog = data.get('progress', data)
        assert prog['watch_percentage'] == 50

# ─── Artefact Tables ───

def test_artefact_tables_created():
    from backend.app.artefacts import _db
    conn = _db()
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('course_evidence_requirements','learner_artefacts')").fetchall()]
    conn.close()
    assert 'course_evidence_requirements' in tables
    assert 'learner_artefacts' in tables

# ─── Artefact Admin ───

def test_create_evidence_requirement():
    h = admin_headers()
    r = client.post('/api/artefacts/admin/requirements',
        data={
            'course_id': 'C1',
            'module_id': 'M1',
            'requirement_code': 'REQ-INTEG-01',
            'title': 'Reflection on Finnish Values',
            'instructions': 'Write a 500-word reflection',
            'evidence_type': 'portfolio_evidence',
            'required_for_certificate': '1',
            'sequence_order': '1',
            'status': 'active'
        },
        headers=h)
    if r.status_code == 422:
        r = client.post('/api/artefacts/admin/requirements',
            json={
                'course_id': 'C1',
                'module_id': 'M1',
                'requirement_code': 'REQ-INTEG-01',
                'title': 'Reflection on Finnish Values',
                'instructions': 'Write a 500-word reflection',
            },
            headers=h)
    assert r.status_code in (200, 201)

def test_get_requirements():
    h = learner_headers()
    client.post('/api/enrollments', json={'course_id': 'C1'}, headers=h)
    r = client.get('/api/artefacts/requirements?course_id=C1', headers=h)
    assert r.status_code == 200
    data = r.json()
    reqs = data.get('requirements', data) if isinstance(data, dict) else data
    if isinstance(reqs, list):
        assert len(reqs) >= 1

# ─── Artefact Learner Upload ───

def test_upload_and_review_artefact():
    h = learner_headers()
    client.post('/api/enrollments', json={'course_id': 'C1'}, headers=h)
    pdf_data = b'%PDF-1.4 fake pdf content for testing purposes'
    r = client.post('/api/artefacts/learner/upload',
        files={'file': ('my-reflection.pdf', io.BytesIO(pdf_data), 'application/pdf')},
        data={
            'course_id': 'C1',
            'module_id': 'M1',
            'title': 'My Reflection on Finnish Values',
            'description': 'A reflection piece',
            'evidence_type': 'portfolio_evidence'
        },
        headers=h)
    assert r.status_code in (200, 201)
    data = r.json()
    art = data.get('artefact', data)
    assert art['status'] == 'submitted'

    ah = admin_headers()
    r = client.get('/api/artefacts/admin', headers=ah)
    assert r.status_code == 200
    artefacts = r.json()
    arts_list = artefacts.get('artefacts', artefacts) if isinstance(artefacts, dict) else artefacts
    if isinstance(arts_list, list) and arts_list:
        art_id = arts_list[0]['id']
        r = client.patch(f'/api/artefacts/admin/{art_id}/review',
            data={'status': 'approved', 'reviewer_feedback': 'Excellent reflection!'},
            headers=ah)
        assert r.status_code == 200

def test_blocked_file_extension():
    h = learner_headers()
    r = client.post('/api/artefacts/learner/upload',
        files={'file': ('malware.exe', io.BytesIO(b'evil'), 'application/octet-stream')},
        data={'course_id': 'C1', 'title': 'Evil File'},
        headers=h)
    assert r.status_code in (400, 422)

def test_artefact_requires_auth():
    r = client.get('/api/artefacts/learner')
    assert r.status_code == 401
