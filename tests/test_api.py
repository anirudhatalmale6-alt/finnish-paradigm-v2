from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

def auth_headers():
    email='legacy_test@example.com'
    r=client.post('/api/auth/register', json={'name':'Legacy Test','email':email,'password':'StrongPass123','role':'teacher'})
    if r.status_code == 409:
        r=client.post('/api/auth/login', json={'email':email,'password':'StrongPass123'})
    assert r.status_code == 200
    return {'Authorization':'Bearer '+r.json()['access_token']}

def test_courses_available():
    r = client.get('/api/courses')
    assert r.status_code == 200
    assert len(r.json()) >= 12

def test_lms_courses():
    r = client.get('/api/lms/courses')
    assert r.status_code == 200
    courses = r.json()
    assert len(courses) >= 12
    assert courses[0]['course_id'] == 'C1'

def test_booking_create():
    r = client.post('/api/bookings', json={
        'name':'Test User','email':'test@example.com','organisation':'Demo School','audience':'School Management','preferred_date':'2026-06-01','message':'Demo'
    })
    assert r.status_code == 200
    assert r.json()['status'] == 'booked'

def test_lms_module_detail():
    h = auth_headers()
    client.post('/api/enrollments', json={'course_id':'C1'}, headers=h)
    r = client.get('/api/lms/modules/M1', headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data['module']['title'] == 'Finnish-Inspired Values, Equity and Ethical Positioning'
    assert data['locked'] == False
    assert len(data['quizzes']) == 3
    assert len(data['rubrics']) == 3
    assert data['implementation_task'] is not None

def test_lms_module_locked_without_enrollment():
    r = client.get('/api/lms/modules/M1')
    assert r.status_code == 200
    data = r.json()
    assert data['locked'] == True
    assert len(data['quizzes']) == 0

def test_lms_glossary():
    r = client.get('/api/lms/glossary')
    assert r.status_code == 200
    assert len(r.json()) == 13

def test_lms_programme():
    r = client.get('/api/lms/programme')
    assert r.status_code == 200
    data = r.json()
    assert data['brand'] == 'Finland Creative Education Institute'

def test_tvet_modules():
    r = client.get('/api/tvet')
    assert r.status_code == 200
    tvet = r.json()
    assert len(tvet) == 12
    assert tvet[0]['id'] == 'T01'

def test_tvet_detail():
    r = client.get('/api/tvet/T01')
    assert r.status_code == 200
    data = r.json()
    assert 'Competence' in data['title']

def test_consultancy_services():
    r = client.get('/api/consultancy')
    assert r.status_code == 200
    services = r.json()
    assert len(services) == 12
    assert services[0]['id'] == 'S01'

def test_consultancy_detail():
    r = client.get('/api/consultancy/S01')
    assert r.status_code == 200
    data = r.json()
    assert 'Audit' in data['title']

def test_catalogue():
    r = client.get('/api/catalogue')
    assert r.status_code == 200
    data = r.json()
    assert data['total'] >= 36
    assert len(data['courses']) >= 12
    assert len(data['tvet']) == 12
    assert len(data['consultancy']) == 12
