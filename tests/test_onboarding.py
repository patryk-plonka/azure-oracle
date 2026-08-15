from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import respx
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import hash_token
from main import EULA_VERSION, GITHUB_TOKEN_URL, GITHUB_USER_API, app
from models import AuthGrant, License, LifecycleEvent, OAuthState, Token, User


def _start_login(client: TestClient) -> str:
    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 302
    return parse_qs(urlparse(response.headers["location"]).query)["state"][0]


def _mock_github() -> respx.MockRouter:
    router = respx.mock(assert_all_called=False)
    router.post(GITHUB_TOKEN_URL).mock(return_value=Response(200, json={"access_token": "github-secret"}))
    router.get(GITHUB_USER_API).mock(return_value=Response(200, json={"id": 42, "login": "octocat"}))
    return router


def test_eula_requires_valid_onboarding_credential():
    with TestClient(app, base_url="http://localhost") as client:
        response = client.get("/auth/eula")
    assert response.status_code == 401


def test_eula_version_mismatch_preserves_grant(auth_db_session: Session, seeded_onboarding_grant: AuthGrant):
    raw = "fixture-onboarding-grant"
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/auth/eula/accept",
            headers={"Authorization": f"Bearer {raw}"},
            json={"version": "old-version"},
        )
    assert response.status_code == 409
    auth_db_session.refresh(seeded_onboarding_grant)
    assert seeded_onboarding_grant.consumed_at is None


def test_explicit_eula_acceptance_creates_license_events_and_issuance_grant(
    auth_db_session: Session, seeded_onboarding_grant: AuthGrant, seeded_user: User
):
    seeded_user.eula_accepted_at = None
    seeded_user.eula_version = None
    existing_license = auth_db_session.scalar(
        select(License).where(License.user_id == seeded_user.id)
    )
    assert existing_license is not None
    auth_db_session.delete(existing_license)
    auth_db_session.commit()

    raw = "fixture-onboarding-grant"
    with TestClient(app, base_url="http://localhost") as client:
        response = client.get("/auth/eula", headers={"Authorization": f"Bearer {raw}"})
        assert response.status_code == 200
        assert response.json()["version"] == EULA_VERSION
        response = client.post(
            "/auth/eula/accept",
            headers={"Authorization": f"Bearer {raw}"},
            json={"version": EULA_VERSION},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["next_action"] == "create_token"
    assert body["issuance_credential"]
    auth_db_session.refresh(seeded_onboarding_grant)
    assert seeded_onboarding_grant.consumed_at is not None
    grants = auth_db_session.scalars(select(AuthGrant).where(AuthGrant.user_id == seeded_user.id)).all()
    assert {grant.purpose for grant in grants} == {"onboarding", "token_issuance"}
    assert body["issuance_credential"] not in {grant.credential_hash for grant in grants}
    events = auth_db_session.scalars(select(LifecycleEvent).where(LifecycleEvent.user_id == seeded_user.id)).all()
    assert {event.event_type for event in events} == {"eula_accepted", "demo_license_assigned"}
    assert auth_db_session.scalar(select(License).where(License.user_id == seeded_user.id)) is not None


def test_callback_alone_does_not_create_entitlement(auth_db_session: Session):
    with TestClient(app, base_url="http://localhost") as client, _mock_github():
        state = _start_login(client)
        response = client.get("/auth/callback", params={"code": "code", "state": state})
    assert response.status_code == 200
    assert auth_db_session.scalar(select(User).where(User.github_id == 42)) is not None
    assert auth_db_session.scalar(select(License)) is None
    assert auth_db_session.scalar(select(LifecycleEvent)) is None
    assert auth_db_session.scalar(select(Token)) is None


def test_callback_provider_failure_preserves_state(auth_db_session: Session):
    with TestClient(app, base_url="http://localhost") as client, respx.mock() as router:
        router.post(GITHUB_TOKEN_URL).mock(return_value=Response(500))
        state = _start_login(client)
        response = client.get("/auth/callback", params={"code": "code", "state": state})
    assert response.status_code == 502
    state_row = auth_db_session.scalar(select(OAuthState).where(OAuthState.state_hash == hash_token(state)))
    assert state_row is not None
    assert state_row.consumed_at is None


def test_expired_onboarding_grant_is_rejected(auth_db_session: Session, seeded_onboarding_grant: AuthGrant):
    seeded_onboarding_grant.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    auth_db_session.commit()
    with TestClient(app, base_url="http://localhost") as client:
        response = client.get("/auth/eula", headers={"Authorization": "Bearer fixture-onboarding-grant"})
    assert response.status_code == 401
