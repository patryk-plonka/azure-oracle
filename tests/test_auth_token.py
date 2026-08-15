"""Integration tests for one-time token issuance and owner expiration."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import hash_token
from main import app
from models import AuthGrant, License, LifecycleEvent, Token, User


def _client() -> TestClient:
    return TestClient(app, base_url="http://localhost")


def _issuance_credential(db: Session, user: User, value: str = "valid-issuance-credential") -> str:
    db.add(
        AuthGrant(
            id=uuid4(),
            user_id=user.id,
            credential_hash=hash_token(value),
            purpose="token_issuance",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
    )
    db.commit()
    return value


def _create_token(client: TestClient, credential: str, name: str = "primary"):
    return client.post(
        "/auth/tokens",
        json={"name": name},
        headers={"Authorization": f"Bearer {credential}"},
    )


def test_token_returns_once_for_valid_issuance_credential(auth_db_session: Session, seeded_user: User):
    credential = _issuance_credential(auth_db_session, seeded_user)
    response = _create_token(_client(), credential)

    assert response.status_code == 200
    data = response.json()
    assert data["token"]
    assert data["token_id"]
    assert data["name"] == "primary"
    assert data["expires_at"]
    assert _create_token(_client(), credential).status_code == 401


def test_token_rejects_malformed_and_wrong_purpose_credentials(
    auth_db_session: Session, seeded_user: User
):
    client = _client()
    assert _create_token(client, "not-a-grant").status_code == 401
    auth_db_session.add(
        AuthGrant(
            id=uuid4(),
            user_id=seeded_user.id,
            credential_hash=hash_token("onboarding-grant"),
            purpose="onboarding",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
    )
    auth_db_session.commit()
    assert _create_token(client, "onboarding-grant").status_code == 401


def test_token_rejects_expired_issuance_credential(auth_db_session: Session, seeded_user: User):
    credential = "expired-issuance-credential"
    auth_db_session.add(
        AuthGrant(
            id=uuid4(),
            user_id=seeded_user.id,
            credential_hash=hash_token(credential),
            purpose="token_issuance",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    auth_db_session.commit()
    response = _create_token(_client(), credential)
    assert response.status_code == 401


def test_token_requires_active_demo_license(auth_db_session: Session, seeded_user_no_license: User):
    credential = _issuance_credential(auth_db_session, seeded_user_no_license)
    response = _create_token(_client(), credential)
    assert response.status_code == 403


def test_token_stored_as_hash_only(auth_db_session: Session, seeded_user: User):
    raw = _create_token(_client(), _issuance_credential(auth_db_session, seeded_user)).json()["token"]

    stored = auth_db_session.scalars(
        select(Token).where(Token.user_id == seeded_user.id)
    ).all()
    hashes = {row.token_hash for row in stored}

    assert hash_token(raw) in hashes
    assert raw not in hashes
    event = auth_db_session.scalar(select(LifecycleEvent).where(LifecycleEvent.user_id == seeded_user.id))
    assert event is not None
    assert event.event_type == "token_created"
    assert raw not in (event.metadata_json or "")


def test_owner_can_expire_a_target_token(auth_db_session: Session, seeded_user: User):
    client = _client()
    actor = _create_token(client, _issuance_credential(auth_db_session, seeded_user, "actor-credential"), "actor").json()["token"]
    target_response = _create_token(
        client, _issuance_credential(auth_db_session, seeded_user, "target-credential"), "target"
    )
    target = target_response.json()

    assert client.get("/auth/probe", headers={"Authorization": f"Bearer {target['token']}"}).status_code == 200

    expire = client.post(
        f"/auth/tokens/{target['token_id']}/expire", headers={"Authorization": f"Bearer {actor}"}
    )
    assert expire.status_code == 200
    assert expire.json()["expired"] is True
    assert expire.json()["token_id"] == target["token_id"]

    assert client.get("/auth/probe", headers={"Authorization": f"Bearer {target['token']}"}).status_code == 401


def test_other_user_cannot_expire_a_token(auth_db_session: Session, seeded_user: User):
    other = User(id=uuid4(), github_id=54321, login="other", eula_version="demo-v1")
    auth_db_session.add(other)
    auth_db_session.flush()
    auth_db_session.add(License(user_id=other.id, license_type="demo", is_active=True))
    auth_db_session.commit()
    client = _client()
    actor = _create_token(client, _issuance_credential(auth_db_session, seeded_user, "actor-credential"))
    target = _create_token(client, _issuance_credential(auth_db_session, other, "other-credential"))

    response = client.post(
        f"/auth/tokens/{target.json()['token_id']}/expire",
        headers={"Authorization": f"Bearer {actor.json()['token']}"},
    )
    assert response.status_code == 404


def test_malformed_token_id_is_non_disclosing(auth_db_session: Session, seeded_user: User):
    actor = _create_token(
        _client(), _issuance_credential(auth_db_session, seeded_user, "actor-credential")
    )

    response = _client().post(
        "/auth/tokens/not-a-token-id/expire",
        headers={"Authorization": f"Bearer {actor.json()['token']}"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Token not found"}
