from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

def admin_headers():
    email = 'admin_test_stripe@example.com'
    r = client.post('/api/auth/register', json={'name': 'Admin Test', 'email': email, 'password': 'StrongPass123', 'role': 'learner'})
    if r.status_code == 409:
        r = client.post('/api/auth/login', json={'email': email, 'password': 'StrongPass123'})
    assert r.status_code == 200
    token = r.json()['access_token']
    import sqlite3, os
    from backend.app.main import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET role='admin' WHERE email=?", (email,))
    conn.commit()
    conn.close()
    r2 = client.post('/api/auth/login', json={'email': email, 'password': 'StrongPass123'})
    assert r2.status_code == 200
    return {'Authorization': 'Bearer ' + r2.json()['access_token']}

def test_stripe_readiness_endpoint():
    h = admin_headers()
    r = client.get('/api/stripe/readiness', headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data['customer_portal_supported'] is True
    assert data['refunds_supported'] is True
    assert 'payment' in data['checkout_modes_supported']
    assert 'subscription' in data['checkout_modes_supported']
    assert 'checkout.session.completed' in data['supported_events']

def test_stripe_readiness_requires_admin():
    r = client.get('/api/stripe/readiness')
    assert r.status_code in (401, 403)
