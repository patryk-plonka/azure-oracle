from fastapi.testclient import TestClient

from main import app


def test_health_endpoint():
    # Use base_url="http://localhost" so the Host header matches the default
    # allowed hosts and bypasses TrustedHostMiddleware rejection
    client = TestClient(app, base_url="http://localhost")
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
