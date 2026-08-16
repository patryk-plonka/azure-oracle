import os
from collections.abc import Callable

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker


class DatabaseConfigurationError(ValueError):
    """Raised when a PostgreSQL connection URL is absent or invalid."""


def get_database_url(database_url: str | None = None) -> str:
    """Return a validated PostgreSQL URL without exposing it in errors."""
    value = database_url or os.getenv("DATABASE_URL")
    if not value:
        raise DatabaseConfigurationError("A PostgreSQL database URL is required.")

    try:
        parsed_url = make_url(value)
    except ArgumentError as error:
        raise DatabaseConfigurationError("A valid PostgreSQL database URL is required.") from error

    if parsed_url.get_backend_name() != "postgresql":
        raise DatabaseConfigurationError("A PostgreSQL database URL is required.")

    if parsed_url.drivername == "postgresql":
        return parsed_url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)

    return value


def create_database_engine(database_url: str | None = None) -> Engine:
    return create_engine(
        get_database_url(database_url),
        pool_pre_ping=True,
        connect_args={"prepare_threshold": None},
    )


def create_session_factory(database_url: str | None = None) -> Callable[[], Session]:
    return sessionmaker(bind=create_database_engine(database_url), expire_on_commit=False)