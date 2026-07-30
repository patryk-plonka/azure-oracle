import os
from collections.abc import Generator

import pytest

# Set auth env vars with test defaults BEFORE importing main (which gates on them at module level)
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("APP_URL", "http://localhost")
os.environ.setdefault("GITHUB_OAUTH_CLIENT_ID", "test-client-id")
os.environ.setdefault("GITHUB_OAUTH_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("TOKEN_HASH_SALT", "test-token-hash-salt")

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

from database import create_database_engine


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
        connection.execute(text("TRUNCATE tokens, licenses, users, limitations, sources"))
    return test_engine