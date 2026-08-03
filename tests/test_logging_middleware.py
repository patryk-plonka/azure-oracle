"""Integration tests for RequestLoggingMiddleware and Risk #4 secret stripping."""

import logging
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from main import app
from tests.conftest import RAW_TOKEN


class _ListHandler(logging.Handler):
    """Collect records for one test without sharing pytest handler state."""

    def __init__(self, records: list[logging.LogRecord]) -> None:
        super().__init__(logging.INFO)
        self.records = records

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def log_records() -> Generator[list[logging.LogRecord], None, None]:
    """Capture non-propagating application and uvicorn error records per test."""
    records: list[logging.LogRecord] = []
    handler = _ListHandler(records)
    loggers = [
        logging.getLogger("azure_oracle.request"),
        logging.getLogger("azure_oracle.error"),
        logging.getLogger("uvicorn.error"),
    ]
    levels = {logger: logger.level for logger in loggers}
    disabled = {logger: logger.disabled for logger in loggers}
    for logger in loggers:
        logger.setLevel(logging.INFO)
        logger.disabled = False
        logger.addHandler(handler)
    try:
        yield records
    finally:
        for logger in loggers:
            logger.removeHandler(handler)
            logger.setLevel(levels[logger])
            logger.disabled = disabled[logger]


def _log_text(records: list[logging.LogRecord]) -> str:
    """Join captured log messages for secret-leakage assertions."""
    return " ".join(record.getMessage() for record in records)


@pytest.fixture
def raising_route() -> Generator[str, None, None]:
    """Add and remove a route that retains a secret before raising an error."""
    path = "/__test_raise"

    async def raise_unhandled_exception() -> None:
        retained_token = RAW_TOKEN
        assert retained_token
        raise RuntimeError("boom")

    app.add_api_route(path, raise_unhandled_exception)
    route = app.router.routes[-1]
    try:
        yield path
    finally:
        app.router.routes.remove(route)


# ---------------------------------------------------------------------------
# Success-path tests
# ---------------------------------------------------------------------------


class TestSuccessPath:
    def test_request_logged_on_success(self, log_records):
        """GET /health → 200; assert one INFO record with method, path, status."""
        with TestClient(app, base_url="http://localhost") as client:
            response = client.get("/health")
        assert response.status_code == 200

        request_records = [
            record
            for record in log_records
            if record.name == "azure_oracle.request"
        ]
        assert len(request_records) >= 1, "Expected at least one request log record"
        text = _log_text(log_records)
        assert "GET /health 200" in text
        assert RAW_TOKEN not in text

    def test_authorization_header_redacted_on_success(self, log_records, seeded_token):
        """GET /auth/probe with valid token → 200; raw token never appears in logs."""
        raw, _ = seeded_token
        with TestClient(app, base_url="http://localhost") as client:
            response = client.get(
                "/auth/probe", headers={"Authorization": f"Bearer {raw}"}
            )
        assert response.status_code == 200

        text = _log_text(log_records)
        assert "Authorization" not in text
        assert raw not in text
        assert RAW_TOKEN not in text


# ---------------------------------------------------------------------------
# Error-path tests (Risk #4 core)
# ---------------------------------------------------------------------------


def test_request_logged_on_401(log_records):
    """GET /auth/probe without token → 401; log shows 401, no secret."""
    with TestClient(app, base_url="http://localhost") as client:
        response = client.get("/auth/probe")
    assert response.status_code == 401

    text = _log_text(log_records)
    assert "GET /auth/probe 401" in text
    assert RAW_TOKEN not in response.text
    assert RAW_TOKEN not in text


def test_request_logged_on_403(
    log_records,
    auth_db_session,
    seeded_user_inactive_license,
):
    """GET /auth/probe with inactive-license token → 403; no secret in log or body."""
    from datetime import UTC, datetime, timedelta

    from auth import hash_token
    from models import Token

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

    with TestClient(app, base_url="http://localhost") as client:
        response = client.get(
            "/auth/probe", headers={"Authorization": f"Bearer {raw}"}
        )
    assert response.status_code == 403

    text = _log_text(log_records)
    assert "GET /auth/probe 403" in text
    assert raw not in response.text
    assert raw not in text
    assert RAW_TOKEN not in text


def test_500_logs_scrubbed_traceback_no_secret(log_records, raising_route):
    """Unhandled exception → 500; scrubbed traceback logged, no secret leaked."""
    with TestClient(
        app, base_url="http://localhost", raise_server_exceptions=False
    ) as client:
        response = client.get(raising_route)
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}

    error_records = [
        record for record in log_records if record.name == "azure_oracle.error"
    ]
    assert len(error_records) >= 1, "Expected at least one error log record"
    error_msg = error_records[0].getMessage()
    assert "RuntimeError" in error_msg
    assert "boom" in error_msg
    assert "Traceback (most recent call last)" in error_msg
    text = _log_text(log_records)
    assert RAW_TOKEN not in text


def test_500_no_uvicorn_traceback(log_records, raising_route):
    """Unhandled exception → no uvicorn.error traceback (SuppressUvicornTracebackFilter)."""
    with TestClient(
        app, base_url="http://localhost", raise_server_exceptions=False
    ) as client:
        response = client.get(raising_route)
    assert response.status_code == 500

    uvicorn_traceback_records = [
        record
        for record in log_records
        if record.name == "uvicorn.error" and record.exc_info is not None
    ]
    assert len(uvicorn_traceback_records) == 0, (
        "SuppressUvicornTracebackFilter should drop uvicorn.error exc_info records"
    )


def test_raw_token_not_in_error_body(log_records, raising_route):
    """500 response body never contains the raw token, even when sent as Auth header."""
    with TestClient(
        app, base_url="http://localhost", raise_server_exceptions=False
    ) as client:
        response = client.get(
            raising_route, headers={"Authorization": f"Bearer {RAW_TOKEN}"}
        )
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    assert RAW_TOKEN not in response.text
    assert RAW_TOKEN not in _log_text(log_records)