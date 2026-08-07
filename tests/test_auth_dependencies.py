"""Unit tests for auth.py Depends() functions."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.exceptions import HTTPException
from sqlalchemy.orm import Session

from auth import get_current_user, hash_token, require_active_license
from models import AuthGrant, License, LifecycleEvent, Token, User


def test_auth_lifecycle_records_preserve_only_hashed_grants(
    auth_db_session: Session, seeded_user: User
):
    raw_grant = "onboarding-credential-never-persisted"
    lifecycle_event = LifecycleEvent(
        id=uuid4(),
        user_id=seeded_user.id,
        event_type="eula_accepted",
        metadata_json='{"eula_version":"demo-v1"}',
    )
    grant = AuthGrant(
        id=uuid4(),
        user_id=seeded_user.id,
        credential_hash=hash_token(raw_grant),
        purpose="onboarding",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    auth_db_session.add_all([lifecycle_event, grant])
    auth_db_session.commit()

    persisted_user = auth_db_session.get(User, seeded_user.id)
    assert persisted_user is not None
    assert persisted_user.eula_version == "demo-v1"
    assert persisted_user.lifecycle_events == [lifecycle_event]
    assert persisted_user.auth_grants == [grant]
    assert grant.credential_hash == hash_token(raw_grant)
    assert raw_grant not in grant.credential_hash
    assert lifecycle_event.metadata_json == '{"eula_version":"demo-v1"}'


class TestGetCurrentUser:
    def test_no_header(self, auth_db_session: Session):
        with pytest.raises(HTTPException) as exc:
            get_current_user(authorization=None, db=auth_db_session)
        assert exc.value.status_code == 401

    def test_malformed_header(self, auth_db_session: Session):
        with pytest.raises(HTTPException) as exc:
            get_current_user(authorization="NotBearer xyz", db=auth_db_session)
        assert exc.value.status_code == 401

    def test_invalid_token(self, auth_db_session: Session):
        with pytest.raises(HTTPException) as exc:
            get_current_user(authorization="Bearer bad-token", db=auth_db_session)
        assert exc.value.status_code == 401

    def test_expired_token(self, auth_db_session: Session, seeded_user: User):
        raw = "expired-token-raw-32-bytes!!!!"
        token_hash = hash_token(raw)
        token_row = Token(
            user_id=seeded_user.id,
            token_hash=token_hash,
            name="expired",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        auth_db_session.add(token_row)
        auth_db_session.commit()

        with pytest.raises(HTTPException) as exc:
            get_current_user(authorization=f"Bearer {raw}", db=auth_db_session)
        assert exc.value.status_code == 401

    def test_valid_token(self, auth_db_session: Session, seeded_user: User, seeded_token: tuple[str, Token]):
        raw, _ = seeded_token
        user = get_current_user(authorization=f"Bearer {raw}", db=auth_db_session)
        assert user.id == seeded_user.id
        assert user.login == "testuser"


class TestRequireActiveLicense:
    def test_active_license(self, auth_db_session: Session, seeded_user: User):
        user = require_active_license(user=seeded_user, db=auth_db_session)
        assert user.id == seeded_user.id

    def test_inactive_license(self, auth_db_session: Session, seeded_user_inactive_license: User):
        with pytest.raises(HTTPException) as exc:
            require_active_license(user=seeded_user_inactive_license, db=auth_db_session)
        assert exc.value.status_code == 403

    def test_no_license(self, auth_db_session: Session, seeded_user_no_license: User):
        with pytest.raises(HTTPException) as exc:
            require_active_license(user=seeded_user_no_license, db=auth_db_session)
        assert exc.value.status_code == 403

    def test_license_deactivated_between_requests(
        self, auth_db_session: Session, seeded_user: User
    ):
        # First call: license is active
        user = require_active_license(user=seeded_user, db=auth_db_session)
        assert user.id == seeded_user.id

        # Deactivate the license
        license_row = auth_db_session.query(License).filter_by(user_id=seeded_user.id).first()
        assert license_row is not None
        license_row.is_active = False
        auth_db_session.commit()

        # Second call: license is now inactive
        with pytest.raises(HTTPException) as exc:
            require_active_license(user=seeded_user, db=auth_db_session)
        assert exc.value.status_code == 403


class TestHashToken:
    def test_deterministic(self):
        h1 = hash_token("abc")
        h2 = hash_token("abc")
        assert h1 == h2

    def test_different_inputs(self):
        h1 = hash_token("abc")
        h2 = hash_token("def")
        assert h1 != h2