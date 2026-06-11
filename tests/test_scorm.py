
import io, os, zipfile, json
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

def admin_headers():
    r = client.post('/api/auth/login', json={'email': os.getenv('ADMIN_EMAIL', 'admin@fcei.edu'), 'password': os.getenv('ADMIN_PASSWORD', 'ChangeMeNow!123')})
    assert r.status_code == 200
    return {'Authorization': 'Bearer ' + r.json()['access_token']}

def learner_headers():
    email = 'scorm_test_learner@example.com'
    r = client.post('/api/auth/register', json={'name': 'SCORM Learner', 'email': email, 'password': 'StrongPass123', 'role': 'teacher'})
    if r.status_code == 409:
        r = client.post('/api/auth/login', json={'email': email, 'password': 'StrongPass123'})
    assert r.status_code == 200
    return {'Authorization': 'Bearer ' + r.json()['access_token']}

def make_sample_scorm_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('imsmanifest.xml', '''<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="test-scorm" version="1.0"
  xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
  xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2">
  <metadata><schema>ADL SCORM</schema><schemaversion>1.2</schemaversion></metadata>
  <organizations default="ORG1">
    <organization identifier="ORG1">
      <title>Test SCORM Module</title>
      <item identifier="ITEM1" identifierref="RES1"><title>Test</title></item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="RES1" type="webcontent" adlcp:scormtype="sco" href="index.html">
      <file href="index.html"/>
    </resource>
  </resources>
</manifest>''')
        zf.writestr('index.html', '<html><body><h1>Test SCORM Content</h1></body></html>')
    buf.seek(0)
    return buf

def test_scorm_tables_created():
    from backend.app.scorm import _db
    conn = _db()
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'scorm%'").fetchall()]
    conn.close()
    assert 'scorm_packages' in tables
    assert 'scorm_attempts' in tables
    assert 'scorm_module_assignments' in tables

def test_upload_scorm_package():
    h = admin_headers()
    buf = make_sample_scorm_zip()
    r = client.post('/api/scorm/admin/upload',
        files={'package': ('test-scorm.zip', buf, 'application/zip')},
        data={'package_name': 'Test SCORM Package', 'package_version': '1.0'},
        headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data['status'] == 'uploaded'
    assert data['package_id'] > 0
    assert data['launch_file'] == 'index.html'
    assert data['scorm_version'] == '1.2'
    return data['package_id']

def test_upload_requires_admin():
    h = learner_headers()
    buf = make_sample_scorm_zip()
    r = client.post('/api/scorm/admin/upload',
        files={'package': ('test.zip', buf, 'application/zip')},
        data={'package_name': 'Test'},
        headers=h)
    assert r.status_code == 403

def test_list_packages():
    h = admin_headers()
    r = client.get('/api/scorm/admin/packages', headers=h)
    assert r.status_code == 200
    packages = r.json()
    assert len(packages) >= 1
    assert packages[0]['package_name']

def test_assign_package_to_module():
    h = admin_headers()
    buf = make_sample_scorm_zip()
    upload = client.post('/api/scorm/admin/upload',
        files={'package': ('assign-test.zip', buf, 'application/zip')},
        data={'package_name': 'Assign Test'},
        headers=h)
    pkg_id = upload.json()['package_id']
    r = client.post(f'/api/scorm/admin/assign/M1/{pkg_id}', headers=h)
    assert r.status_code == 200
    assert r.json()['status'] == 'assigned'

def test_module_scorm_info():
    r = client.get('/api/scorm/modules/M1/info')
    assert r.status_code == 200
    data = r.json()
    assert data['has_scorm'] == True
    assert data['scorm_version'] == '1.2'

def test_create_scorm_session():
    h = learner_headers()
    client.post('/api/enrollments', json={'course_id': 'C1'}, headers=h)
    r = client.post('/api/scorm/modules/M1/sessions', headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data['session_id']
    assert data['player_url'].startswith('/api/scorm/player/')
    assert 'lt=' in data['player_url']
    return data

def test_session_requires_enrollment():
    email = 'scorm_no_enroll@example.com'
    r = client.post('/api/auth/register', json={'name': 'No Enroll', 'email': email, 'password': 'StrongPass123', 'role': 'learner'})
    if r.status_code == 409:
        r = client.post('/api/auth/login', json={'email': email, 'password': 'StrongPass123'})
    h = {'Authorization': 'Bearer ' + r.json()['access_token']}
    r = client.post('/api/scorm/modules/M1/sessions', headers=h)
    assert r.status_code == 403

def test_scorm_player_loads():
    session_data = test_create_scorm_session()
    r = client.get(session_data['player_url'])
    assert r.status_code == 200
    assert 'SCORM' in r.text
    assert 'LMSInitialize' in r.text

def test_scorm_state_and_commit():
    session_data = test_create_scorm_session()
    lt = session_data['player_url'].split('lt=')[1]
    sid = session_data['session_id']

    r = client.get(f'/api/scorm/session/{sid}/state?lt={lt}')
    assert r.status_code == 200
    cmi = r.json()['cmi']
    assert cmi['cmi.core.lesson_status'] == 'not attempted'
    assert cmi['cmi.core.entry'] == 'ab-initio'

    cmi['cmi.core.lesson_status'] = 'incomplete'
    cmi['cmi.core.lesson_location'] = 'page-2'
    cmi['cmi.core.score.raw'] = '85'
    r = client.post(f'/api/scorm/session/{sid}/commit?lt={lt}', json={'cmi': cmi})
    assert r.status_code == 200
    assert r.json()['lesson_status'] == 'incomplete'

    cmi['cmi.core.lesson_status'] = 'completed'
    cmi['cmi.core.session_time'] = '00:05:30'
    r = client.post(f'/api/scorm/session/{sid}/finish?lt={lt}', json={'cmi': cmi})
    assert r.status_code == 200
    assert r.json()['completed'] == True

def test_scorm_content_served():
    session_data = test_create_scorm_session()
    lt = session_data['player_url'].split('lt=')[1]
    sid = session_data['session_id']

    from backend.app.scorm import _db, verify_launch_token
    payload = verify_launch_token(lt)
    pkg_id = payload['pkg']

    r = client.get(f'/api/scorm/content/{pkg_id}/index.html?lt={lt}')
    assert r.status_code == 200
    assert 'Test SCORM Content' in r.text

def test_scorm_progress_report():
    h = admin_headers()
    r = client.get('/api/scorm/admin/progress', headers=h)
    assert r.status_code == 200
    assert 'progress' in r.json()

def test_invalid_launch_token():
    r = client.get('/api/scorm/session/fakeid/state?lt=bad.token')
    assert r.status_code == 401

def test_deactivate_package():
    h = admin_headers()
    buf = make_sample_scorm_zip()
    upload = client.post('/api/scorm/admin/upload',
        files={'package': ('deactivate-test.zip', buf, 'application/zip')},
        data={'package_name': 'Deactivate Test'},
        headers=h)
    pkg_id = upload.json()['package_id']
    r = client.delete(f'/api/scorm/admin/packages/{pkg_id}', headers=h)
    assert r.status_code == 200
    assert r.json()['status'] == 'deactivated'
