from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

def test_stripe_readiness_endpoint():
    r = client.get('/api/stripe/readiness')
    assert r.status_code == 200
    data = r.json()
    assert data['customer_portal_supported'] is True
    assert data['refunds_supported'] is True
    assert 'payment' in data['checkout_modes_supported']
    assert 'subscription' in data['checkout_modes_supported']
    assert 'checkout.session.completed' in data['supported_events']
