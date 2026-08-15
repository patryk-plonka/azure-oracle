# Deploy Skeleton + Health Implementation Plan

## Overview

Replace the hello-world stub in `main.py` with a minimal FastAPI application that exposes a `/health` endpoint, and add Railway deployment configuration (`railway.json`) so the app can be deployed and health-checked on Railway.

## Current State Analysis

- `main.py` is a hello-world stub: a `main()` function that prints a string. No FastAPI `app` object, no routes, no middleware.
- `pyproject.toml` already declares `fastapi>=0.139.2` and `uvicorn>=0.51.0` as dependencies.
- `.python-version` pins `3.12` (Railpack runtime-drift mitigation already in place).
- `uv.lock` is committed (Railpack auto-detects `uv` from it).
- No `railway.json`, `railway.toml`, `Procfile`, or `Dockerfile` exists.
- No tests, no middleware, no configuration files beyond `pyproject.toml`.

## Desired End State

A FastAPI `app` object exists at `main:app` with a `/health` endpoint returning `{"status": "ok"}` and HTTP 200. A `railway.json` declares the start command and health-check path. The app can be started locally with `uv run uvicorn main:app` and the `/health` endpoint responds. The project is ready for `railway up` (the actual deploy is a separate human-gated step per `deploy-plan.md`).

### Key Discoveries

- Railway's health-check host must be added to FastAPI's `TrustedHostMiddleware` allowed hosts, or zero-downtime deploys fail the health gate in a way that looks like an app bug (`infrastructure.md` §Unknown Unknowns).
- Railway injects `$PORT` as an environment variable; the start command must use `$PORT`, not a hard-coded port (`infrastructure.md` §4).
- Railway terminates TLS at its edge; the app receives HTTP internally — no app-level HTTPS redirect needed (`infrastructure.md` §Operational Story).

## What We're NOT Doing

- No database wiring (F-02's scope).
- No auth, OAuth, tokens, or license logic (F-03's scope).
- No logging middleware or secret stripping (F-04's scope).
- No actual `railway up` deployment (human-gated, per `deploy-plan.md`).
- No CI/CD pipeline (parked in roadmap).
- No Dockerfile (Railpack auto-detects from `uv.lock`).
- No readiness endpoint with dependency checks (F-02 adds this when Postgres is wired).

## Implementation Approach

Single phase: replace `main.py` with a FastAPI app, add `railway.json`, write a minimal test, verify locally. The scope is intentionally small — this is the foundation every downstream slice builds on, and it must be rock-solid but minimal.

## Phase 1: FastAPI Skeleton + Railway Config

### Overview

Create the deployable FastAPI app with `/health`, configure Railway deployment, and verify the skeleton works locally.

### Changes Required:

#### 1. FastAPI Application

**File**: `main.py`

**Intent**: Replace the hello-world stub with a FastAPI `app` object that exposes a `/health` endpoint returning `{"status": "ok"}` with HTTP 200. Add `TrustedHostMiddleware` with allowed hosts configurable via the `ALLOWED_HOSTS` environment variable (comma-separated), defaulting to `["localhost", "127.0.0.1"]` for local development. The Railway health-check host is added to this list at deploy time via a Railway service variable — no code change needed.

**Contract**: The app object must be importable as `main:app`. The `/health` endpoint is a `GET` route returning a JSON body `{"status": "ok"}`. The `ALLOWED_HOSTS` env var is read at startup; if unset, the middleware allows `localhost` and `127.0.0.1`. The `TrustedHostMiddleware` is applied to the app.

#### 2. Railway Configuration

**File**: `railway.json`

**Intent**: Declare the start command and health-check path so Railway knows how to run and verify the app. This replaces manual dashboard configuration with a version-controlled config.

**Contract**: The file specifies the start command `uv run uvicorn main:app --host 0.0.0.0 --port $PORT` and the health-check path `/health`. The `$PORT` variable is injected by Railway at runtime — never hard-coded.

#### 3. Test

**File**: `tests/test_health.py`

**Intent**: Add a minimal test that verifies the `/health` endpoint returns 200 with the expected JSON body. Uses FastAPI's `TestClient` (from `httpx`) — no running server needed.

**Contract**: A single test function that creates a `TestClient` from the `main:app` object with `base_url="http://localhost"` (so the Host header matches the default allowed hosts and bypasses `TrustedHostMiddleware` rejection), sends `GET /health`, and asserts status code 200 and body `{"status": "ok"}`. The test must pass with `uv run pytest`.

#### 4. Test Dependency

**File**: `pyproject.toml`

**Intent**: Add `pytest` and `httpx` as dev dependencies so the test can run. FastAPI's `TestClient` requires `httpx`.

**Contract**: Add a `[dependency-groups]` section with a `dev` group containing `pytest` and `httpx`. Run `uv sync` to update `uv.lock`.

### Success Criteria:

#### Automated Verification:

- App starts locally: `uv run uvicorn main:app --host 0.0.0.0 --port 8000` starts without errors
- Health endpoint responds: `curl http://localhost:8000/health` returns `{"status": "ok"}` with HTTP 200
- Tests pass: `uv run pytest tests/ -v` passes with 1 test
- Type checking: no import errors when running `uv run python -c "from main import app; print(app)"`

#### Manual Verification:

- Railway deploy succeeds: `railway up` builds and deploys (human-gated, not automated in this phase)
- `GET /health` returns 200 over HTTPS at the Railway URL
- Railway's health check passes (service shows as healthy in dashboard)

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the Railway deployment was successful before proceeding.

---

## Testing Strategy

### Unit Tests:

- `/health` returns 200 with `{"status": "ok"}`
- `TrustedHostMiddleware` rejects requests with unrecognized hosts (optional, low priority for skeleton)

### Manual Testing Steps:

1. Start the app locally with `uv run uvicorn main:app --port 8000`
2. `curl http://localhost:8000/health` → `{"status": "ok"}`
3. Deploy to Railway with `railway up` (human-gated)
4. `curl https://<railway-url>/health` → `{"status": "ok"}`
5. Verify Railway dashboard shows service as healthy

## Performance Considerations

None at this stage. The skeleton has no dependencies, no database, no external calls. The `/health` endpoint is a static JSON response — well under the PRD's <800 ms p95 target.

## Migration Notes

No migration needed. This is a greenfield skeleton replacing a hello-world stub. No data, no state, no existing users.

## References

- Deploy plan entry gates: `context/deployment/deploy-plan.md` §1
- Infrastructure risk (health-check host): `context/foundation/infrastructure.md` §Unknown Unknowns
- PRD health endpoint requirement: `context/foundation/prd.md` FR-013
- Railway start command: `context/foundation/infrastructure.md` §4

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: FastAPI Skeleton + Railway Config

#### Automated

- [x] 1.1 App starts locally without errors — 8f906ec
- [x] 1.2 Health endpoint returns 200 with correct JSON — 8f906ec
- [x] 1.3 Tests pass (`uv run pytest tests/ -v`) — 8f906ec
- [x] 1.4 App object importable (`from main import app`) — 8f906ec

#### Manual

- [x] 1.5 Railway deploy succeeds (`railway up`)
- [x] 1.6 Health endpoint returns 200 over HTTPS at Railway URL
- [x] 1.7 Railway health check passes in dashboard
