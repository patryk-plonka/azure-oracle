from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import respx
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import hash_token
from main import GITHUB_TOKEN_URL, GITHUB_USER_API, app
from models import AuthGrant, OAuthState, User


def _login_state(client: TestClient) -> str:
    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert "github.com/login/oauth/authorize" in location
    return parse_qs(urlparse(location).query)["state"][0]


def _register_github(router: respx.MockRouter, github_id: int = 7, login: str = "octocat") -> None:
    router.post(GITHUB_TOKEN_URL).mock(return_value=Response(200, json={"access_token": "github-access-token"}))
    router.get(GITHUB_USER_API).mock(return_value=Response(200, json={"id": github_id, "login": login}))


def test_login_persists_only_hash_of_opaque_state(auth_db_session: Session):
    with TestClient(app, base_url="http://localhost") as client:
        state = _login_state(client)
    state_row = auth_db_session.scalar(select(OAuthState))
    assert state_row is not None
    assert state_row.state_hash == hash_token(state)
    assert state not in state_row.state_hash
    assert state_row.expires_at > datetime.now(UTC)


def test_callback_consumes_state_once_and_creates_owned_onboarding_grant(auth_db_session: Session):
    with TestClient(app, base_url="http://localhost") as client, respx.mock() as router:
        _register_github(router)
        state = _login_state(client)
        response = client.get("/auth/callback", params={"code": "code", "state": state})
        replay = client.get("/auth/callback", params={"code": "code", "state": state})
    assert response.status_code == 200
    body = response.json()
    assert body["next_action"] == "accept_eula"
    assert body["login"] == "octocat"
    assert body["onboarding_credential"]
    assert replay.status_code == 400
    user = auth_db_session.scalar(select(User).where(User.github_id == 7))
    assert user is not None
    assert user.eula_accepted_at is None
    grant = auth_db_session.scalar(select(AuthGrant).where(AuthGrant.user_id == user.id))
    assert grant is not None
    assert grant.purpose == "onboarding"
    assert grant.credential_hash == hash_token(body["onboarding_credential"])
    assert body["onboarding_credential"] not in grant.credential_hash


def test_expired_and_malformed_state_are_rejected(auth_db_session: Session):
    auth_db_session.add(OAuthState(state_hash=hash_token("expired-state"), expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    auth_db_session.commit()
    with TestClient(app, base_url="http://localhost") as client:
        expired = client.get("/auth/callback", params={"code": "code", "state": "expired-state"})
        malformed = client.get("/auth/callback", params={"code": "code", "state": "unknown-state"})
    assert expired.status_code == 400
    assert malformed.status_code == 400


def test_multiple_states_for_one_identity_create_one_user(auth_db_session: Session):
    with TestClient(app, base_url="http://localhost") as client, respx.mock() as router:
        _register_github(router, github_id=99, login="same-user")
        state_one = _login_state(client)
        state_two = _login_state(client)
        first = client.get("/auth/callback", params={"code": "one", "state": state_one})
        second = client.get("/auth/callback", params={"code": "two", "state": state_two})
    assert first.status_code == 200
    assert second.status_code == 200
    users = auth_db_session.scalars(select(User).where(User.github_id == 99)).all()
    assert len(users) == 1
    grants = auth_db_session.scalars(select(AuthGrant).where(AuthGrant.user_id == users[0].id)).all()
    assert len(grants) == 2
