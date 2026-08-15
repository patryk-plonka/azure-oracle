# Observability Floor - Plan Brief

> Full plan: `context/changes/observability-logging-floor/plan.md`
> Research: `context/changes/observability-logging-floor/research.md`

## What & Why

F-04 provides the minimum operational logging floor: one secret-safe request
record for every HTTP response and one scrubbed error record for every unhandled
exception. The Phase 2 revision corrects a Starlette control-flow assumption so
the guardrail covers handled authentication failures as well as 500 errors.

## Starting Point

Phase 1 added request/error loggers, a clean 500 response, a uvicorn traceback
filter, and access-log suppression. The first Phase 2 tests exposed that
`BaseHTTPMiddleware` cannot observe every required response and that production
loggers with `propagate=False` need direct test capture.

## Desired End State

`GET /health`, protected-route 401/403 responses, and unhandled 500 errors each
emit exactly one appropriate application request record. A 500 also emits a
scrubbed traceback, while the response body and all emitted records exclude the
raw bearer token and other frame-local secret values.

## Key Decisions Made

| Decision | Choice | Why | Source |
| --- | --- | --- | --- |
| Request observation | Pure ASGI middleware | It sees response-start events from the inner exception layer, including 401/403. | Plan |
| 500 logging owner | Custom `Exception` handler | `ServerErrorMiddleware` produces the 500 outside user middleware. | Plan |
| Test capture | Direct per-test handler | Named production loggers do not propagate to pytest's root handler. | Plan |
| 500 test trigger | Temporary route fixture | It exercises the real error path without permanently changing the singleton app. | Plan |
| Client lifecycle | Context-managed `TestClient` | Each test closes its client before logger fixture teardown. | Plan |

## Scope

**In scope:**

- Pure-ASGI request-status logging for 200, 401, and 403 responses.
- Handler-owned request/error logging for 500 responses.
- Deterministic integration tests for secret stripping on success and failure paths.
- Auth/license test cookbook documentation.

**Out of scope:**

- Structured logs, correlation IDs, metrics, audit trails, and new packages.
- An app-factory refactor or production-route changes.
- Request, response, header, or query-string logging.

## Architecture / Approach

The pure-ASGI middleware wraps the user application and records timing while it
forwards ASGI messages. It logs when it sees `http.response.start`; the outer
server-error handler logs the 500 request plus its scrubbed traceback because
that response is generated beyond user middleware. Tests attach isolated
in-memory handlers directly to the three named loggers and remove them after
each test.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Logging Middleware + Error Handler + Wiring | Baseline logging floor and deployment wiring. | Unobserved or duplicate production logs. |
| 2. Corrected Logging + Risk #4 Secret-Leakage Verification | Correct status/error ownership, deterministic tests, and cookbook guidance. | Token or traceback-local secret leak. |

**Prerequisites:** Phase 1 is committed as `5f02db8`; test PostgreSQL is
available through `TEST_DATABASE_URL`.

**Estimated effort:** One implementation session plus manual verification.

## Open Risks & Assumptions

- The temporary raising-route fixture must remove only the route it creates.
- Logger fixture teardown must restore every logger level and handler it changes.
- `SuppressUvicornTracebackFilter` must continue to pass non-traceback uvicorn
  errors through unchanged.

## Success Criteria (Summary)

- The focused logging suite passes sequentially and within the full test suite.
- 200, 401, 403, and 500 tests all prove raw-token absence from records and
  responses.
- Ruff and mypy pass, and the cookbook records the secret-stripping pattern.# Observability Floor — Plan Brief

> Full plan: `context/changes/observability-logging-floor/plan.md`
> Research: `context/changes/observability-logging-floor/research.md`

## What & Why

Add a request + error logging middleware with secret-stripping to the FastAPI
app — the minimal logging floor the PRD NFR requires ("every request and error
is logged, with secrets stripped"). This is sequenced before S-01 (the north-star
query endpoint) so the "no secrets or tokens appear in any log" guardrail is
enforced before the first end-to-end query exercise, not bolted on after.

## Starting Point

The app has zero application logging today and exactly one middleware
(`TrustedHostMiddleware` at `main.py:57`). All 20 errors are `HTTPException`
with static `detail` strings (no secrets in any). Unhandled exceptions fall
through to Starlette's default 500, which logs a full traceback — including
frame locals that may contain `access_token`, `raw_token`, or `raw`. The
`database.py:11-26` module already redacts `DATABASE_URL` from its errors —
prior secret-stripping art F-04 extends to all logs and error bodies.

## Desired End State

Every request emits one log line (method, path, status, duration) via a
dedicated `"azure_oracle.request"` logger. Unhandled exceptions emit a scrubbed
traceback (frame locals stripped) via `"azure_oracle.error"` and return a clean
`{"detail": "Internal Server Error"}`. No secret — raw token, `access_token`,
`SECRET_KEY`, `TOKEN_HASH_SALT`, `DATABASE_URL`, `GITHUB_OAUTH_CLIENT_SECRET` —
appears in any log or error body, including on the error path. Uvicorn's access
log is silenced; the middleware is the sole request logger.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| Middleware type | `BaseHTTPMiddleware` via `app.add_middleware` | F-03 frame established middleware = infrastructure, not `Depends()` | Research |
| Logging library | stdlib `logging` only | FR-014 (structured logging) is Parked; F-03 set zero-new-packages posture | Research |
| Middleware ordering | Outermost (added after TrustedHost) | Logs all requests including host-rejected 400s for full visibility | Plan |
| 500 traceback handling | Log scrubbed traceback, suppress Starlette default | Starlette's default logs frame locals (leak risk); custom handler + scrubbed log is the sole error source | Plan |
| Uvicorn access log | Silence with `--no-access-log` | Middleware is sole request logger; avoids duplication | Plan |
| Risk #4 test ownership | F-04 owns the secret-leakage tests | Tests live with the code they verify; single change delivers middleware + tests | Plan |
| Log content | method, path, status, duration only | No request/response bodies logged (raw token lives in `/auth/token` response body) | Research |
| New env vars | None | Keep it simple; uvicorn `--log-level` controls root level if needed later | Plan |

## Scope

**In scope:**
- `logging_middleware.py` (new root-level module: scrub utilities + `RequestLoggingMiddleware`)
- `main.py` wiring (register middleware outermost + `@app.exception_handler(Exception)` for clean 500)
- `railway.json` (`--no-access-log` on start command)
- `tests/test_logging_middleware.py` (success + error path, `caplog` + `seeded_token`)
- `test-plan.md` §6.4 cookbook update

**Out of scope:**
- Structured/correlated logging (FR-014, Parked)
- Request/response body logging
- Metrics, Prometheus, audit trail (FR-015, Parked)
- New packages (`structlog`, `loguru`, etc.)
- App-factory refactor
- Changes to existing `HTTPException` detail strings

## Architecture / Approach

```
Request → RequestLoggingMiddleware (outermost) → TrustedHostMiddleware → routes
                ↓                                          ↓
         logs method/path/status/duration          host check (400 if rejected)
                ↓
         on Exception: logs scrubbed traceback (azure_oracle.error)
                ↓
         @app.exception_handler(Exception) → {"detail": "Internal Server Error"}
```

One new module (`logging_middleware.py`) with three pieces: `_scrub_headers`
(redacts `Authorization` → `Bearer ***`), `_scrub_traceback` (formats traceback
without frame locals), and `RequestLoggingMiddleware` (logs each request + scrubbed
error). The custom `Exception` handler suppresses Starlette's default traceback
logging so the middleware's scrubbed version is the sole error source.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Middleware + error handler + wiring | `logging_middleware.py`, `main.py` registration, `railway.json` `--no-access-log` | `BaseHTTPMiddleware` + exception handler interaction — `call_next` may not re-raise after handler converts to response; verify with a 500 test |
| 2. Tests — Risk #4 verification | `tests/test_logging_middleware.py` (success + 401/403/500 paths), `test-plan.md` §6.4 | Test must exercise the error/exception path, not just success (Risk #4 anti-pattern) |

**Prerequisites:** F-01 (deploy skeleton, done), F-03 (auth scaffold, done — provides `seeded_token` fixture and the `Authorization` header surface to test against)
**Estimated effort:** ~1-2 sessions across 2 phases

## Open Risks & Assumptions

- **`BaseHTTPMiddleware` + exception handler interaction**: when `@app.exception_handler(Exception)` is registered, Starlette's exception middleware catches the exception and converts it to a response *before* it propagates back through `BaseHTTPMiddleware.dispatch`. The middleware's `try/except` around `call_next` may not see the exception re-raised — it may instead see a 500 response. The implementer must verify this with a test that triggers a real 500 and confirm the scrubbed traceback appears in `caplog`; if `call_next` does not re-raise, the middleware should detect 500 status codes and log the error from a stored exception reference or accept that the exception handler is the sole 500 path (adjusting the plan accordingly).
- **`_scrub_traceback` completeness**: the scrubbing utility must handle all traceback formats Starlette/Python produce; a test with a real exception is the verification, not a regex assumption.

## Success Criteria (Summary)

- Every request (including host-rejected 400s and 500s) emits one log line with no secret
- Unhandled exceptions emit a scrubbed traceback with no frame-local values
- The 500 response body is `{"detail": "Internal Server Error"}` with no secret
- `RAW_TOKEN` never appears in any `caplog` record on any path (success, 401, 403, 500)
- Uvicorn's access log is silenced; the middleware is the sole request logger
