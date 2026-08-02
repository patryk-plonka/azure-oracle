import logging
import time
import traceback
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


def _scrub_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of headers with Authorization redacted to 'Bearer ***'."""
    scrubbed = dict(headers)
    for key in list(scrubbed.keys()):
        if key.lower() == "authorization":
            scrubbed[key] = "Bearer ***"
    return scrubbed


def _scrub_traceback(exc: Exception) -> str:
    """Format a traceback with frame locals replaced by '<redacted>'.

    Uses traceback.extract_tb to rebuild the traceback string without
    local variable values, preserving file paths, line numbers, function
    names, and the exception type/message.
    """
    extracted = traceback.extract_tb(exc.__traceback__)
    lines: list[str] = []
    lines.append("Traceback (most recent call last):\n")
    for frame in extracted:
        lines.append(
            f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}\n'
        )
        if frame.line:
            lines.append(f"    {frame.line}\n")
    lines.extend(traceback.format_exception_only(type(exc), exc))
    return "".join(lines)


class SuppressUvicornTracebackFilter(logging.Filter):
    """Drop uvicorn.error records that contain exc_info (traceback records).

    Uvicorn emits "Exception in ASGI application" records because
    ServerErrorMiddleware re-raises after the custom exception handler
    runs. This filter drops those redundant tracebacks so the
    middleware's scrubbed traceback is the sole error log.

    Non-traceback error logs (startup errors, config errors, etc.)
    pass through unchanged.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return record.exc_info is None


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request (method, path, status, duration) and scrubbed
    tracebacks on unhandled exceptions.

    Uses two loggers:
    - ``azure_oracle.request`` (INFO) — one line per request
    - ``azure_oracle.error``   (ERROR) — scrubbed traceback on 500

    No request body, response body, or header values are logged.
    """

    def __init__(self, app):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.logger = logging.getLogger("azure_oracle.request")
        self.error_logger = logging.getLogger("azure_oracle.error")

    async def dispatch(  # type: ignore[override]
        self, request: Request, call_next: Any
    ) -> Response:
        start = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            self.logger.info(
                "%s %s 500 %.0fms",
                request.method,
                request.url.path,
                duration_ms,
            )
            self.error_logger.error(
                "Unhandled exception: %s\n%s",
                type(exc).__name__,
                _scrub_traceback(exc),
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        self.logger.info(
            "%s %s %d %.0fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response