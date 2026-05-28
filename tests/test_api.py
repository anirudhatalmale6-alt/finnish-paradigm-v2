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
    assert len(courses) == 12
    assert courses[0]['course_id'] == 'C1'

def test_booking_create():
    r = client.post('/api/bookings', json={
        'name':'Test User','email':'test@example.com','organisation':'Demo School','audience':'School Management','preferred_date':'2026-06-01','message':'Demo'
    })
    assert r.status_code == 200
    assert r.json()['status'] == 'booked'

def test_lms_module_detail():
    r = client.get('/api/lms/modules/M1')
    assert r.status_code == 200
    data = r.json()
    assert data['module']['title'] == 'Finnish-Inspired Values, Equity and Ethical Positioning'
    assert len(data['quizzes']) == 3
    assert len(data['rubrics']) == 3
    assert data['implementation_task'] is not None

def test_lms_glossary():
    r = client.get('/api/lms/glossary')
    assert r.status_code == 200
    assert len(r.json()) == 13

def test_lms_programme():
    r = client.get('/api/lms/programme')
    assert r.status_code == 200
    data = r.json()
    assert data['brand'] == 'Finland Creative Education Institute'
