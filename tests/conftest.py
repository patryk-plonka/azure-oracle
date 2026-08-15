import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

# Set auth env vars with test defaults BEFORE importing main (which gates on them at module level)
os.environ.setdefault("APP_URL", "http://localhost")
os.environ.setdefault("GITHUB_OAUTH_CLIENT_ID", "test-client-id")
os.environ.setdefault("GITHUB_OAUTH_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("TOKEN_HASH_SALT", "test-token-hash-salt")

# Route auth.py's SessionFactory to the test database
_test_db_url = os.getenv("TEST_DATABASE_URL", "")
if _test_db_url:
    os.environ["DATABASE_URL"] = _test_db_url

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from auth import hash_token
from database import create_database_engine
from models import AuthGrant, License, LifecycleEvent, OAuthState, Token, User


def run_migrations(engine: Engine, revision: str) -> None:
    config = Config("alembic.ini")
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


@pytest.fixture(scope="session")
def test_engine() -> Generator[Engine, None, None]:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        raise RuntimeError("TEST_DATABASE_URL is required for PostgreSQL import tests.")

    engine = create_database_engine(database_url)
    run_migrations(engine, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def clean_test_database(test_engine: Engine) -> Engine:
    with test_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE oauth_states, auth_grants, lifecycle_events, tokens, licenses, users, "
                "limitations, sources"
            )
        )
    return test_engine


# ------- Auth test fixtures -------

RAW_TOKEN = "test-raw-token-32-bytes-long!!!"


@pytest.fixture
def auth_db_session(clean_test_database: Engine) -> Generator[Session, None, None]:
    """Per-test DB session with clean tables and seeded auth data."""
    SessionLocal = sessionmaker(bind=clean_test_database, expire_on_commit=False)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def seeded_user(auth_db_session: Session) -> User:
    """Seed a user with EULA accepted and an active Demo license."""
    user = User(
        id=uuid4(),
        github_id=12345,
        login="testuser",
        eula_accepted_at=datetime.now(UTC),
        eula_version="demo-v1",
    )
    auth_db_session.add(user)
    auth_db_session.flush()

    license_row = License(user_id=user.id, license_type="demo", is_active=True)
    auth_db_session.add(license_row)
    auth_db_session.commit()
    return user


@pytest.fixture
def seeded_token(auth_db_session: Session, seeded_user: User) -> tuple[str, Token]:
    """Seed a valid, non-expired token for the seeded user. Returns (raw, Token)."""
    token_hash = hash_token(RAW_TOKEN)
    token_row = Token(
        id=uuid4(),
        user_id=seeded_user.id,
        token_hash=token_hash,
        name="default",
        expires_at=datetime.now(UTC) + timedelta(days=90),
    )
    auth_db_session.add(token_row)
    auth_db_session.commit()
    return RAW_TOKEN, token_row


@pytest.fixture
def seeded_user_no_eula(auth_db_session: Session) -> User:
    """Seed a user without EULA acceptance."""
    user = User(
        id=uuid4(),
        github_id=99999,
        login="noeula",
        eula_accepted_at=None,
    )
    auth_db_session.add(user)
    auth_db_session.commit()
    return user


@pytest.fixture
def seeded_user_no_license(auth_db_session: Session) -> User:
    """Seed a user with EULA but no license."""
    user = User(
        id=uuid4(),
        github_id=77777,
        login="nolicense",
        eula_accepted_at=datetime.now(UTC),
        eula_version="demo-v1",
    )
    auth_db_session.add(user)
    auth_db_session.commit()
    return user


@pytest.fixture
def seeded_user_inactive_license(auth_db_session: Session) -> User:
    """Seed a user with EULA and an inactive license."""
    user = User(
        id=uuid4(),
        github_id=88888,
        login="inactive",
        eula_accepted_at=datetime.now(UTC),
    )
    auth_db_session.add(user)
    auth_db_session.flush()

    license_row = License(user_id=user.id, license_type="demo", is_active=False)
    auth_db_session.add(license_row)
    auth_db_session.commit()
    return user


@pytest.fixture
def seeded_user_active_non_demo_license(auth_db_session: Session) -> User:
    """Seed a user whose active license is outside the Demo-only MVP policy."""
    user = User(
        id=uuid4(),
        github_id=66666,
        login="nondemo",
        eula_accepted_at=datetime.now(UTC),
        eula_version="demo-v1",
    )
    auth_db_session.add(user)
    auth_db_session.flush()
    auth_db_session.add(License(user_id=user.id, license_type="trial", is_active=True))
    auth_db_session.commit()
    return user


@pytest.fixture
def seeded_onboarding_grant(auth_db_session: Session, seeded_user: User) -> AuthGrant:
    """Seed an unconsumed, short-lived opaque onboarding credential hash."""
    grant = AuthGrant(
        id=uuid4(),
        user_id=seeded_user.id,
        credential_hash=hash_token("fixture-onboarding-grant"),
        purpose="onboarding",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    auth_db_session.add(grant)
    auth_db_session.commit()
    return grant


@pytest.fixture
def seeded_oauth_state(auth_db_session: Session) -> OAuthState:
    """Seed a valid pre-identity OAuth state without a user relationship."""
    state = OAuthState(
        id=uuid4(),
        state_hash=hash_token("fixture-oauth-state"),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    auth_db_session.add(state)
    auth_db_session.commit()
    return state


@pytest.fixture
def seeded_lifecycle_event(auth_db_session: Session, seeded_user: User) -> LifecycleEvent:
    """Seed non-secret lifecycle evidence for the authenticated user."""
    event = LifecycleEvent(
        id=uuid4(),
        user_id=seeded_user.id,
        event_type="eula_accepted",
        metadata_json='{"eula_version":"demo-v1"}',
    )
    auth_db_session.add(event)
    auth_db_session.commit()
    return event