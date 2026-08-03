"""Integration tests for /auth/token and /auth/token/expire routes."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import hash_token
from main import _create_token_grant, _sign_user_id, app
from models import Token, User


def _client() -> TestClient:
    return TestClient(app, base_url="http://localhost")


def test_token_returns_token_for_valid_user(auth_db_session: Session, seeded_user: User):
    grant = _create_token_grant(seeded_user.id)
    response = _client().get(f"/auth/token?grant={grant}")

    assert response.status_code == 200
    data = response.json()
    assert data["token"]
    assert data["name"] == "default"
    assert data["expires_at"]


def test_token_rejects_bad_signature(seeded_user: User):
    response = _client().get(f"/auth/token?grant={seeded_user.id}.9999999999.deadbeef")
    assert response.status_code == 400


def test_token_rejects_expired_grant(seeded_user: User):
    grant = _create_token_grant(
        seeded_user.id, expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )
    response = _client().get(f"/auth/token?grant={grant}")

    assert response.status_code == 400


def test_token_without_eula_returns_400(auth_db_session: Session, seeded_user_no_eula: User):
    grant = _create_token_grant(seeded_user_no_eula.id)
    response = _client().get(f"/auth/token?grant={grant}")
    assert response.status_code == 400


def test_token_without_active_license_returns_403(
    auth_db_session: Session, seeded_user_no_license: User
):
    grant = _create_token_grant(seeded_user_no_license.id)
    response = _client().get(f"/auth/token?grant={grant}")
    assert response.status_code == 403


def test_token_stored_as_hash_only(auth_db_session: Session, seeded_user: User):
    grant = _create_token_grant(seeded_user.id)
    raw = _client().get(f"/auth/token?grant={grant}").json()["token"]

    stored = auth_db_session.scalars(
        select(Token).where(Token.user_id == seeded_user.id)
    ).all()
    hashes = {row.token_hash for row in stored}

    assert hash_token(raw) in hashes
    assert raw not in hashes


def test_expire_rejects_token_for_subsequent_probe(auth_db_session: Session, seeded_user: User):
    client = _client()
    grant = _create_token_grant(seeded_user.id)
    raw = client.get(f"/auth/token?grant={grant}").json()["token"]
    sig = _sign_user_id(seeded_user.id)

    assert client.get("/auth/probe", headers={"Authorization": f"Bearer {raw}"}).status_code == 200

    expire = client.post(
        f"/auth/token/expire?user_id={seeded_user.id}&sig={sig}", json={"token": raw}
    )
    assert expire.status_code == 200
    assert expire.json() == {"expired": True}

    assert client.get("/auth/probe", headers={"Authorization": f"Bearer {raw}"}).status_code == 401
