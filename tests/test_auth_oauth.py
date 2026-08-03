from fastapi.testclient import TestClient

from main import app


def test_login_redirects_to_github_with_302():
    response = TestClient(app, base_url="http://localhost").get(
        "/auth/login", follow_redirects=False
    )

    assert response.status_code == 302
    assert "github.com/login/oauth/authorize" in response.headers["location"]