"""Integration tests for /auth/probe route."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from auth import hash_token
from main import app
from models import Token, User


def test_probe_no_token():
    client = TestClient(app, base_url="http://localhost")
    response = client.get("/auth/probe")
    assert response.status_code == 401


def test_probe_expired_token(auth_db_session: Session, seeded_user: User):
    raw = "expired-probe-token-32-bytes!!"
    token_hash = hash_token(raw)
    token_row = Token(
        user_id=seeded_user.id,
        token_hash=token_hash,
        name="expired",
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    auth_db_session.add(token_row)
    auth_db_session.commit()

    client = TestClient(app, base_url="http://localhost")
    response = client.get("/auth/probe", headers={"Authorization": f"Bearer {raw}"})
    assert response.status_code == 401


def test_probe_inactive_license(auth_db_session: Session, seeded_user_inactive_license: User):
    raw = "inactive-license-token-32-bytes!"
    token_hash = hash_token(raw)
    token_row = Token(
        user_id=seeded_user_inactive_license.id,
        token_hash=token_hash,
        name="default",
        expires_at=datetime.now(UTC) + timedelta(days=90),
    )
    auth_db_session.add(token_row)
    auth_db_session.commit()

    client = TestClient(app, base_url="http://localhost")
    response = client.get("/auth/probe", headers={"Authorization": f"Bearer {raw}"})
    assert response.status_code == 403


def test_probe_valid(auth_db_session: Session, seeded_user: User, seeded_token: tuple[str, Token]):
    raw, _ = seeded_token
    client = TestClient(app, base_url="http://localhost")
    response = client.get("/auth/probe", headers={"Authorization": f"Bearer {raw}"})
    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is True
    assert data["user"] == "testuser"