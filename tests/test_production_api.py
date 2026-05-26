
from fastapi.testclient import TestClient
from backend.app.main import app
client = TestClient(app)

def test_health_and_catalogue():
    assert client.get('/api/health').status_code == 200
    assert len(client.get('/api/courses').json()) >= 3

def test_auth_enrollment_assessment_flow():
    email='teacher_test@example.com'
    r=client.post('/api/auth/register', json={'name':'Teacher Test','email':email,'password':'StrongPass123','role':'teacher'})
    if r.status_code == 409:
        r=client.post('/api/auth/login', json={'email':email,'password':'StrongPass123'})
    assert r.status_code == 200
    token=r.json()['access_token']; h={'Authorization':'Bearer '+token}
    assert client.post('/api/enrollments', json={'course_id':'fcfp'}, headers=h).status_code == 200
    s=client.post('/api/assessment/start', json={'learner_name':'Teacher Test','course_id':'fcfp'}, headers=h).json()
    assert s['session_id']
    item=s['next_item']
    ans=client.post('/api/assessment/answer', json={'session_id':s['session_id'],'item_id':item['id'],'selected':item['options'][0]}, headers=h)
    assert ans.status_code == 200
