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
    assert len(r.json()) >= 3

def test_booking_create():
    r = client.post('/api/bookings', json={
        'name':'Test User','email':'test@example.com','organisation':'Demo School','audience':'School Management','preferred_date':'2026-06-01','message':'Demo'
    })
    assert r.status_code == 200
    assert r.json()['status'] == 'booked'

def test_adaptive_assessment_flow():
    h = auth_headers()
    r = client.post('/api/assessment/start', json={'learner_name':'Learner','course_id':'fcfp'}, headers=h)
    assert r.status_code == 200
    payload = r.json()
    assert payload['session_id']
    item = payload['next_item']
    assert item['question']
    answer = item['options'][0]
    r2 = client.post('/api/assessment/answer', json={'session_id':payload['session_id'],'item_id':item['id'],'selected':answer}, headers=h)
    assert r2.status_code == 200
    assert 'ability' in r2.json()
