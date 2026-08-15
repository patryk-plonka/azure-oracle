---
date: 2026-08-02T00:00:00+00:00
researcher: GitHub Copilot
git_commit: b83cc98ed159075ab9a18d17306fd02cd1ef20b3
branch: main
repository: azure-oracle
topic: "F-04 observability-logging-floor — request/error logging middleware with secret-stripping"
tags: [research, codebase, logging, middleware, observability, secrets, fastapi]
status: complete
last_updated: 2026-08-02
last_updated_by: GitHub Copilot
---

# Research: F-04 observability-logging-floor

**Date**: 2026-08-02
**Researcher**: GitHub Copilot
**Git Commit**: b83cc98ed159075ab9a18d17306fd02cd1ef20b3
**Branch**: main
**Repository**: azure-oracle

## Research Question

What is the current state of the codebase with respect to logging, middleware,
error handling, and secrets — and what conventions must the F-04
(observability-logging-floor) implementation plan be consistent with? F-04
delivers the minimal logging floor: request + error logging middleware with
secrets stripped from logs and error bodies (PRD NFR, must-have). Full
structured/correlated logging (FR-014) is Parked and out of scope.

## Summary

The codebase is a greenfield FastAPI app with **zero application logging** and
**exactly one middleware** (`TrustedHostMiddleware`). All errors are raised as
`HTTPException` with static `detail` strings; there is no global exception
handler, so unhandled exceptions fall through to Starlette's default 500. No
secret currently appears in any `HTTPException.detail` string, and `database.py`
already redacts the connection URL from its configuration errors — a prior
secret-redaction convention F-04 extends to all logs and HTTP error bodies.

The F-03 (auth-scaffold) change established the decisive convention: **middleware
= infrastructure (host validation, logging); `Depends()` = auth**. F-04's logging
middleware therefore belongs as `app.add_middleware(...)`, not as a dependency.
F-03 also adopted a "zero/minimal new packages" posture and explicitly deferred
secret-stripping to F-04 while avoiding logging raw tokens itself.

The highest-risk leak surfaces a naive logging middleware must handle are: (1)
the `Authorization: Bearer <raw-token>` header on every protected request, (2)
the raw token returned in the `/auth/token` response body, and (3) traceback
frame locals (`access_token`, `raw_token`, `raw`) if the middleware logs full
tracebacks on the 500 path. The test plan (§3 Phase 2, Risk #4) requires that
tests exercise the **error/exception path**, not just success logs — the explicit
anti-pattern is "asserting only the success log; never exercising the failure
path."

## Detailed Findings

### Current middleware state

- **Only one middleware is registered**: `TrustedHostMiddleware`
  (`main.py:13` import, `main.py:57` `app.add_middleware(...)`). `allowed_hosts`
  is built from the `ALLOWED_HOSTS` env var with default
  `"localhost,127.0.0.1,healthcheck.railway.app"` (`main.py:53-55`).
- A workspace-wide grep for `add_middleware|Middleware|@app.middleware|BaseHTTPMiddleware|exception_handler`
  returns only the two `main.py` lines above. There is no `BaseHTTPMiddleware`
  subclass, no `@app.middleware("http")` decorator, no `SessionMiddleware`,
  `CORSMiddleware`, `GZipMiddleware`, or logging middleware anywhere.
- **Middleware ordering**: `add_middleware` wraps the app — the *last* added
  middleware runs *outermost*. `TrustedHostMiddleware` is currently the only one,
  so it runs outermost. The F-03 plan (`auth-scaffold.../plan.md:344`) flags
  middleware ordering as a concern to verify. A logging middleware added
  *after* line 57 becomes the new outermost (sees requests before TrustedHost,
  sees TrustedHost's 400 on the way out); added *before* line 57 it sits inside
  TrustedHost. This is a planning decision for `/10x-plan`.

### Logging configuration — none

- Python's `logging` module is **not used in application code at all**. The only
  `logging` reference is `migrations/env.py:1` (`from logging.config import
  fileConfig`) — Alembic boilerplate, not application logging.
- No `getLogger`, `basicConfig`, `logger`, `log.info`, `log.error` anywhere in
  `main.py`, `auth.py`, `database.py`, `models.py`, or `seed.py`.
- No `structlog`, `loguru`, `python-json-logger`, or any third-party logging
  library (confirmed via `pyproject.toml:6-13` runtime deps and `:16-19` dev
  deps — none are logging libraries).
- The only stdout output is `seed.py:259` (`print(f"Seed import complete: ...")`)
  in the seed script, not a request path.
- **Implication**: Uvicorn's default access log and Starlette's error logging
  are the only logging at runtime; nothing in the app code emits logs.

### Error / exception handling — no global handler

- **No `@app.exception_handler` or `app.add_exception_handler(...)` anywhere.**
  All errors are raised as `HTTPException` with explicit `detail` strings inside
  route handlers and `Depends()` functions. FastAPI's default `HTTPException`
  handler returns `{"detail": "<message>"}` with the given status code.
- Full inventory of `HTTPException` raises (20 total):
  - `auth.py` (Depends chain — 401/403): `auth.py:42` 401 "Missing Authorization
    header"; `auth.py:45` 401 "Invalid Authorization header format"; `auth.py:54`
    401 "Invalid token"; `auth.py:57` 401 "Token expired"; `auth.py:61` 401 "User
    not found"; `auth.py:78` 403 "No active license".
  - `main.py` (route handlers — 400/403/404): `main.py:129` 400 "Invalid state
    format"; `main.py:135` 400 "Invalid state signature"; `main.py:148` 400
    "GitHub token exchange failed"; `main.py:152` 400 "No access_token in GitHub
    response"; `main.py:160` 400 "GitHub user fetch failed"; `main.py:220` 400
    "Invalid user_id format"; `main.py:223` 400 "Invalid user_id signature";
    `main.py:228` 404 "User not found"; `main.py:232` 400 "EULA must be accepted
    before generating a token"; `main.py:242` 403 "No active license";
    `main.py:278` 400 "Invalid user_id format"; `main.py:281` 400 "Invalid
    user_id signature"; `main.py:287` 400 "Provide 'token' or 'token_hash'";
    `main.py:299` 404 "Token not found or does not belong to this user".
- **Startup-time `RuntimeError`** (module import, not HTTP): `main.py:23,27,31,35,39`
  for missing env vars; `auth.py:16` for missing `TOKEN_HASH_SALT`;
  `database.py:18,23,26` `DatabaseConfigurationError` (subclass of `ValueError`)
  for missing/invalid `DATABASE_URL`.
- **Notable prior art**: `database.py:11-26` deliberately does **not** echo the
  URL into the error message — `DatabaseConfigurationError("A PostgreSQL
  database URL is required.")` is a generic string. This is an existing
  secret-stripping precedent F-04 must follow.
- Any unhandled exception (e.g. `httpx` network error in `main.py:140-145`, DB
  error in a handler) falls through to **FastAPI/Starlette's default 500 handler**,
  returning `{"detail": "Internal Server Error"}` and logging the traceback via
  Starlette's `ServerErrorMiddleware` (logger name `"uvicorn.error"` / `"starlette"`).
  There is no app-level catch.

### Secrets in the codebase — where they could leak

Secrets are loaded from env at module import time and held in module-level
variables. None appear in any `HTTPException.detail` string today — the existing
code is already disciplined here. The risk is in headers, query params, response
bodies, and traceback locals that a naive logging middleware would capture.

| # | Secret | Location | Leak surface for a logging middleware |
|---|---|---|---|
| 1 | **Bearer API token (raw)** | `Authorization` header, read `auth.py:37`, stripped `auth.py:47` | Request log if middleware logs headers. **Primary strip target.** |
| 2 | **GitHub OAuth `access_token`** | local var `main.py:150`, used as `Bearer {access_token}` `main.py:157` | Traceback frame locals if exception fires between `main.py:150-160`. Not in any response body. |
| 3 | **Raw token in `/auth/token` response** | `main.py:213` (`raw = secrets.token_urlsafe(32)`), returned `main.py:217` | **Highest-risk leak**: a response-body-logging middleware captures the raw token. The only place a raw token is surfaced. |
| 4 | **`GITHUB_OAUTH_CLIENT_SECRET`** | env `main.py:33`, sent in `httpx.post` body `main.py:142` | Outbound POST body; `httpx` does not log bodies by default. Not in responses. |
| 5 | **`SECRET_KEY`** | env `main.py:21`, HMAC key `main.py:83,104,132` | Never serialized into a response; risk only if env is logged. |
| 6 | **`TOKEN_HASH_SALT`** | env `main.py:37` + `auth.py:14`, hash input `auth.py:33` / `main.py:206` | Same as #5. |
| 7 | **`DATABASE_URL`** (contains Postgres password) | env, read `database.py:16` | Never in responses; **already redacted** in `database.py` errors. Risk only if env is logged. |
| 8 | **`Token.token_hash`** (already SHA-256 hashed) | DB column `models.py:99`; accepted in `/auth/token/expire` body `main.py:287` | A body-logging middleware could capture it; the 404 `detail` at `main.py:299` does not echo it. |
| 9 | **HMAC `state` / `sig` query params** | `/auth/login` builds `state` `main.py:84`; `/auth/token` takes `sig` `main.py:220` | Appear in request URL (query string); uvicorn access log already logs path+query. HMAC-derived, replayable signatures — not raw secrets but sensitive. |
| 10 | **`code` query param** (GitHub OAuth code) | `/auth/callback` `main.py:118` | Short-lived, single-use sensitive; appears in request URL. |

**No `Set-Cookie` secrets** (no `SessionMiddleware`, no cookies set anywhere).
No API-key headers other than `Authorization`.

### Request / response flow

- `main.py:49` `app = FastAPI()` (no constructor args, no `middleware=[...]`).
- `main.py:53-55` build `allowed_hosts`; `main.py:57` register
  `TrustedHostMiddleware`.
- `main.py:60` `SessionFactory = create_session_factory()` (module-level).
- `main.py:64-70` `get_db()` dependency.
- Routes (no `APIRouter` — all on `app`): `GET /health` (`main.py:112`);
  `GET /auth/login` (`main.py:119`); `GET /auth/callback` (`main.py:118`);
  `GET /auth/token` (`main.py:200`); `POST /auth/token/expire` (`main.py:266`);
  `GET /auth/probe` (`main.py:309`, protected via
  `Depends(require_active_license)`).
- **Insertion point for logging middleware**: `main.py:57` (before or after
  `TrustedHostMiddleware` is an ordering decision for `/10x-plan`).

### Test patterns for middleware

- All HTTP-level tests use `fastapi.testclient.TestClient` with
  `base_url="http://localhost"` to satisfy `TrustedHostMiddleware`:
  `tests/test_health.py:8-9`, `tests/test_auth_probe.py:10,18,28,38,55`,
  `tests/test_auth_token.py:11-12`.
- Tests import `from main import app` directly — the real production app. **No
  app-factory pattern, no test-specific app override.** Any middleware added to
  `main.py` is active in every test automatically.
- `conftest.py` fixtures: `test_engine` (session-scoped, runs Alembic to head);
  `clean_test_database` (TRUNCATE per test); `auth_db_session`; `seeded_user`
  (EULA + active license); `seeded_token` (returns `(RAW_TOKEN, Token)` where
  `RAW_TOKEN = "test-raw-token-32-bytes-long!!!"` at `conftest.py:58`);
  `seeded_user_no_eula`, `seeded_user_no_license`, `seeded_user_inactive_license`.
- **Env bootstrap** (`conftest.py:8-13`): sets test env vars via
  `os.environ.setdefault` **before** importing `main` (which fails fast at
  module level). `DATABASE_URL` is redirected to `TEST_DATABASE_URL`
  (`conftest.py:16-18`).
- **No log-capture fixture exists today.** Grep for
  `caplog|capsys|LogCaptureHandler|propagate` across `tests/**` returned zero
  matches. pytest's built-in `caplog` fixture is available (pytest core, pinned
  `>=8.0.0` at `pyproject.toml:18`) — no plugin needed. `caplog` captures
  stdlib `logging` records at the handler pytest installs on the root logger.
  Caveat: uvicorn's `"uvicorn.access"` logger is **not** exercised under
  `TestClient` (TestClient runs the ASGI app, not the uvicorn server), so only
  the middleware's own logger would appear in `caplog`.
- **Unit-vs-integration split**: `tests/test_auth_dependencies.py` tests
  `Depends()` functions directly (no `TestClient`); `test_auth_probe.py` /
  `test_auth_token.py` test through `TestClient`. A middleware test naturally
  follows the `TestClient` integration style.

### Dependencies

- Runtime (`pyproject.toml:6-13`): `alembic>=1.16.0`, `fastapi>=0.139.2`,
  `httpx>=0.27.0`, `psycopg[binary]>=3.2.0`, `sqlalchemy>=2.0.0`,
  `uvicorn>=0.51.0`.
- Dev (`pyproject.toml:16-19`): `pytest>=8.0.0`, `ruff>=0.12.0`, `mypy>=1.17.0`.
- **No logging library installed.** `httpx` already present for `TestClient`.
- Pinned versions (from `uv.lock`): `fastapi` 0.139.2, `starlette` 1.3.1,
  `uvicorn` 0.51.0.
- Available middleware base classes (Starlette 1.3.1):
  `starlette.middleware.base.BaseHTTPMiddleware` (per-request
  `dispatch(request, call_next)`); pure ASGI middleware (3-arg `__call__`).
- Pytest config (`pyproject.toml:21-22`): `pythonpath = ["."]`.

### Uvicorn access-log interaction

- Uvicorn access logs are **on by default**. The start command
  (`railway.json:4`) passes no `--access-log`/`--no-access-log`/`--log-config`
  flags. Uvicorn 0.51 defaults to `access_log=True`, emitting one line per
  request via the `"uvicorn.access"` logger at INFO.
- A middleware-level logger emits its own records via a separate logger (e.g.
  `"azure_oracle.request"`); uvicorn's `"uvicorn.access"` logger continues
  emitting its own line. The two do not collide but produce **two log lines per
  request** unless one is silenced.
- **Uvicorn's access log is not a secret-leak vector**: it logs only method,
  path, status, and round-trip time — not headers or bodies. The leak risk is
  concentrated in any custom middleware that logs headers/bodies, and in error
  `detail` strings (none currently echo secrets, but `auth.py:45` "Invalid
  Authorization header format" is adjacent to the raw `Authorization` value).
- Railway's log stream captures all stdout (`infrastructure.md` "Operational
  Story → Logs" + Devil's Advocate #4) — reinforcing that F-04's middleware is
  the enforcement point for the "no secrets in logs" guardrail.

## Code References

- `main.py:13` — `from starlette.middleware.trustedhost import TrustedHostMiddleware`
- `main.py:49` — `app = FastAPI()` (bare, no constructor args)
- `main.py:53-57` — `allowed_hosts` build + `app.add_middleware(TrustedHostMiddleware, ...)`
- `main.py:112` — `GET /health` (public)
- `main.py:118-167` — `/auth/login`, `/auth/callback` (public)
- `main.py:200-310` — `/auth/token`, `/auth/token/expire`, `/auth/probe` (protected)
- `main.py:213,217` — raw token generated and returned (highest-risk leak for response-body logging)
- `auth.py:37,47` — `Authorization` header read and `raw_token` extracted (primary strip target)
- `auth.py:42-78` — six `HTTPException` raises (401/403) with static `detail` strings
- `database.py:11-26` — `DatabaseConfigurationError` with redacted messages (prior secret-stripping art)
- `models.py:99` — `Token.token_hash` (already SHA-256 hashed)
- `tests/conftest.py:8-13` — env bootstrap before `main` import
- `tests/conftest.py:58` — `RAW_TOKEN` constant for secret-stripping tests
- `tests/conftest.py:82-118` — `seeded_user`, `seeded_token`, no-EULA/no-license fixtures
- `tests/test_health.py:8-9` — `TestClient(app, base_url="http://localhost")` pattern
- `pyproject.toml:6-13` — runtime deps (no logging library)
- `railway.json:4` — start command (no uvicorn log flags)
- `migrations/env.py:1` — only `logging` import in repo (Alembic boilerplate)

## Architecture Insights

### Convention: middleware = infrastructure, `Depends()` = auth

The F-03 frame (`auth-scaffold.../frame.md` "Cross-System Convention")
established a deliberate split: *middleware = infrastructure (host validation,
CORS, logging); `Depends()` = auth*. Quote: *"FastAPI's documented best
practice is `Depends()` for per-route authorization gates and pure ASGI
middleware for cross-cutting infrastructure concerns (host validation, CORS,
logging). The existing `TrustedHostMiddleware` follows this convention."*
**F-04's logging middleware is infrastructure → it belongs as
`app.add_middleware`, NOT as a `Depends()`.** This is the explicit convention
F-04 must follow.

### Convention: root-level module, no package

F-03 created `auth.py` at the repo root (`auth-scaffold.../plan.md` Phase 4 §1:
"File: `auth.py` (new file at project root)"), not in a `routers/` or
`middleware/` package. F-04's logging middleware should follow the same
convention — a root-level module (e.g. `logging_middleware.py`), not a package.

### Convention: env-var fail-fast + mypy alias

`main.py:23-39` reads each env var with `os.getenv()` then `raise
RuntimeError("<VAR> environment variable is required")` if absent, then a
mypy-narrowing alias (`_SECRET_KEY: str = SECRET_KEY  # type: ignore[assignment]`).
F-04 should follow this exact pattern for any new config (e.g. log level), and
must not require env vars beyond those already defaulted in `conftest.py:8-13`
so tests keep working.

### Convention: zero/minimal new packages

F-03 adopted a "zero/minimal new packages" posture (`auth-scaffold.../research.md`
§3, `frame.md`). The PRD demoted FR-014 (full structured logging) to
nice-to-have and the roadmap Parks it (`roadmap.md` F-04: "Full
structured/correlated logging (FR-014) is Parked, not deferred late"). **F-04
should use stdlib `logging` — no `structlog`, no `python-json-logger`** — to
deliver the minimal floor (request + error, secrets stripped) without
correlation IDs or structured fields.

### Convention: plan structure

Both archived foundations follow the same `plan.md` skeleton: Overview →
Current State Analysis → Desired End State → Key Discoveries → What We're NOT
Doing → Implementation Approach → Phase(s) with "Changes Required"
(File/Intent/Contract) + "Success Criteria" (Automated/Manual) + "Implementation
Note" pause-for-human → Testing Strategy → Performance Considerations →
Migration Notes → References → Progress (checkboxes, append commit sha, never
rename titles). F-04's plan should follow this skeleton.

### Convention: redact connection strings in errors (prior art)

`database.py:11-26` already redacts the `DATABASE_URL` from its configuration
errors (`postgres-schema-seed/plan.md` Phase 1 §2 Contract: "create
engines/sessions from the required connection URL without logging the URL or its
credentials" and "Missing or malformed URLs fail with a redacted configuration
error"). **F-04 extends this redaction convention to all logs and HTTP error
bodies.**

### Scope boundary: minimal floor only, FR-014 is Parked

F-04 delivers the **must-have minimal logging floor** (request + error logs,
secrets stripped). It must **NOT** deliver full structured/correlated logging
with correlation IDs — that's FR-014, explicitly Parked (`roadmap.md` F-04;
`prd.md` FR-014 "Priority: nice-to-have" with Socrates note: "a minimal logging
floor (request + error logs, no secrets) moves to NFRs as must-have; full
structured/correlated logging becomes nice-to-have for v1").

### Boundary: F-04 protects the same access boundary as the auth gate

The `testing-auth-license-gate/research.md` "Ownership and Sequencing" notes:
*"Secret stripping is separately owned by F-04. It shares Test Plan Phase 2
because it protects the same access boundary."* F-04's middleware wraps the same
routes the token+license `Depends()` protects.

## Historical Context (from prior changes)

- `context/changes/auth-scaffold-token-license/frame.md` "Cross-System Convention"
  — established middleware = infrastructure, `Depends()` = auth. F-04's logging
  middleware is infrastructure → `app.add_middleware`.
- `context/changes/auth-scaffold-token-license/plan.md` "What We're NOT Doing" —
  *"No secret-stripping middleware — owned by F-04; F-03 avoids logging raw
  tokens."* F-03's code already avoids logging raw tokens; F-04 enforces this
  centrally.
- `context/changes/auth-scaffold-token-license/plan.md:344` — flags middleware
  ordering as a concern to verify (TrustedHost first, logging slots in/around it).
- `context/changes/testing-auth-license-gate/research.md` "Ownership and
  Sequencing" — secret-stripping is owned by F-04, shares Phase 2 because it
  protects the same access boundary as the token+license gate.
- `context/archive/2026-07-20-deploy-skeleton-health/plan.md` "What We're NOT
  Doing" — *"No logging middleware or secret stripping (F-04's scope)"*.
  `TrustedHostMiddleware` is the only middleware added.
- `context/archive/2026-07-29-postgres-schema-seed/plan.md` Phase 1 §2 Contract
  — `database.py` redacts connection URL from errors; prior secret-redaction art.
- `context/foundation/infrastructure.md` "Risk Register" row "Secrets/tokens
  leak into logs" (Likelihood L, Impact H) — Mitigation: *"Enforce the
  'hash-only, never log' rule in code; strip secrets from structured logs and
  error bodies; store values as Railway service variables, not in the repo."*
- `context/foundation/infrastructure.md` "Operational Story → Logs" — *"Ensure
  the minimal logging floor (request + error, secrets stripped) the PRD
  requires."* This is the exact scope of F-04.
- `context/foundation/infrastructure.md` Devil's Advocate #4 — *"No
  secrets-rotation UX beyond env vars. The hard rule 'tokens stored only as
  hashes, never logged' rests entirely on app-level discipline; Railway's log
  stream captures anything printed."* Reinforces F-04 middleware as enforcement
  point.

## Related Research

- `context/changes/auth-scaffold-token-license/research.md` — F-03 research;
  established the middleware-vs-Depends convention and the "zero new packages"
  posture F-04 inherits.
- `context/changes/testing-auth-license-gate/research.md` — Test Plan §3 Phase 2
  research for Risk #3 (token+license gate); explicitly defers Risk #4
  (secret-stripping) to F-04.
- `context/archive/2026-07-20-deploy-skeleton-health/plan.md` — F-01 plan;
  deferred logging middleware to F-04.
- `context/archive/2026-07-29-postgres-schema-seed/plan.md` — F-02 plan;
  established `database.py` connection-URL redaction as prior secret-stripping
  art.

## Open Questions

1. **Middleware ordering** — should the logging middleware run outermost (added
   after `TrustedHostMiddleware` at `main.py:57`, so it logs even
   TrustedHost-rejected 400s) or inside TrustedHost (added before line 57, so it
   only logs host-allowed traffic)? The F-03 plan (`plan.md:344`) flagged
   ordering as a concern. Owner: user. Block: no (resolvable during `/10x-plan`).
2. **Log format** — the PRD NFR requires "every request and error is logged" but
   does not specify a format. Stdlib `logging` with a simple line (method, path,
   status, duration) satisfies the minimal floor; structured JSON is FR-014
   (Parked). Owner: user. Block: no.
3. **Traceback handling on the 500 path** — Starlette's default
   `ServerErrorMiddleware` already logs tracebacks via `"uvicorn.error"`. Should
   F-04's middleware log its own (scrubbed) traceback, suppress the default, or
   rely on the default and only scrub? Traceback frame locals (`access_token`,
   `raw_token`, `raw`) are the leak risk. Owner: user. Block: no.
4. **Uvicorn access-log duplication** — a middleware request logger plus
   uvicorn's default access log produce two lines per request. Silence uvicorn
   via `--no-access-log` in `railway.json`, or leave both? Owner: user. Block: no.
5. **Risk #4 test ownership** — `test-plan.md` §3 Phase 2 covers Risks #3 and
   #4, but `testing-auth-license-gate/research.md` only researched Risk #3.
   Does F-04's plan own the Risk #4 (secret-leakage) tests, or does the
   `testing-auth-license-gate` change continue to own them? Owner: user. Block:
   no (resolvable during `/10x-plan`; either way, the tests must exercise the
   error/exception path per Risk #4's anti-pattern).
