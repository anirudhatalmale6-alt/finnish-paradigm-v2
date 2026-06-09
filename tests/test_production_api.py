
from fastapi.testclient import TestClient
from backend.app.main import app
client = TestClient(app)

def test_health_and_catalogue():
    assert client.get('/api/health').status_code == 200
    courses = client.get('/api/courses').json()
    assert len(courses) >= 12
    assert courses[0]['id'] == 'C1'

def test_auth_enrollment_flow():
    email='teacher_fcei_test@example.com'
    r=client.post('/api/auth/register', json={'name':'Teacher Test','email':email,'password':'StrongPass123','role':'teacher'})
    if r.status_code == 409:
        r=client.post('/api/auth/login', json={'email':email,'password':'StrongPass123'})
    assert r.status_code == 200
    token=r.json()['access_token']; h={'Authorization':'Bearer '+token}
    assert client.post('/api/enrollments', json={'course_id':'C1'}, headers=h).status_code == 200

def test_lms_module_with_quizzes():
    email='teacher_fcei_mod@example.com'
    r=client.post('/api/auth/register', json={'name':'Module Test','email':email,'password':'StrongPass123','role':'teacher'})
    if r.status_code == 409:
        r=client.post('/api/auth/login', json={'email':email,'password':'StrongPass123'})
    assert r.status_code == 200
    h={'Authorization':'Bearer '+r.json()['access_token']}
    client.post('/api/enrollments', json={'course_id':'C1'}, headers=h)
    r = client.get('/api/lms/modules/M1', headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data['module']['title'] == 'Finnish-Inspired Values, Equity and Ethical Positioning'
    assert data['locked'] == False
    assert len(data['quizzes']) == 3
    assert len(data['rubrics']) == 3
    assert data['implementation_task'] is not None
    assert data['implementation_task']['task_id'] == 'TASK-M1'

def test_glossary_and_programme():
    assert len(client.get('/api/lms/glossary').json()) == 13
    prog = client.get('/api/lms/programme').json()
    assert prog['brand'] == 'Finland Creative Education Institute'
    rules = client.get('/api/lms/certificate-rules').json()
    assert rules['quiz_pass_percent'] == 70

def test_tvet_and_consultancy():
    tvet = client.get('/api/tvet').json()
    assert len(tvet) == 12
    assert tvet[0]['id'] == 'T01'
    services = client.get('/api/consultancy').json()
    assert len(services) == 12
    assert services[0]['id'] == 'S01'
    cat = client.get('/api/catalogue').json()
    assert cat['total'] >= 36
