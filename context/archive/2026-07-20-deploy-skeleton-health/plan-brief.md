# Deploy Skeleton + Health — Plan Brief

> Full plan: `context/changes/deploy-skeleton-health/plan.md`

## What & Why

Create the smallest deployable FastAPI application that Railway can health-check. This is Foundation F-01 — the skeleton every downstream slice (data, auth, observability, query core) builds on. Without a running app with a `/health` endpoint, nothing else can be deployed or verified end-to-end.

## Starting Point

`main.py` is a hello-world stub (`print("Hello from azure-oracle!")`). No FastAPI `app` object, no routes, no middleware, no deployment configuration. Dependencies (`fastapi`, `uvicorn`) are declared in `pyproject.toml` but unused. `.python-version` and `uv.lock` are committed and ready for Railpack.

## Desired End State

A FastAPI `app` at `main:app` with a `/health` endpoint returning `{"status": "ok"}`. A `railway.json` declaring the start command and health-check path. The app runs locally and is ready for `railway up`. Railway's health-check host is configurable via the `ALLOWED_HOSTS` environment variable — no code change needed at deploy time.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) |
|---|---|---|
| Endpoint structure | Single `/health` | Simplest skeleton; F-02 adds readiness depth when Postgres is wired |
| Railway config | `railway.json` in repo | Version-controlled, IaC from day one, no dashboard clicks |
| HTTPS enforcement | Railway TLS termination | Zero app code; Railway terminates TLS at the edge |
| TrustedHostMiddleware | `ALLOWED_HOSTS` env var | Railway health-check host added at deploy time without code change |
| Test framework | pytest + httpx | FastAPI's TestClient requires httpx; pytest is the standard |

## Scope

**In scope:**
- FastAPI `app` object at `main:app`
- `GET /health` endpoint returning `{"status": "ok"}`
- `TrustedHostMiddleware` with configurable allowed hosts
- `railway.json` with start command and health-check path
- Minimal test for `/health` endpoint
- `pytest` and `httpx` as dev dependencies

**Out of scope:**
- Database wiring (F-02)
- Auth, OAuth, tokens, licenses (F-03)
- Logging middleware, secret stripping (F-04)
- Actual `railway up` deployment (human-gated)
- CI/CD pipeline (parked)
- Dockerfile (Railpack auto-detects from `uv.lock`)
- Readiness endpoint with dependency checks (F-02)

## Architecture / Approach

Single-file FastAPI app with one route and one middleware. Railway configuration is a static JSON file. The app is stateless with no dependencies — a pure skeleton that returns a static JSON response. `TrustedHostMiddleware` reads allowed hosts from an environment variable, making the Railway health-check host configurable without code changes.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. FastAPI Skeleton + Railway Config | Deployable app with `/health`, `railway.json`, minimal test | Railway health-check host not in `ALLOWED_HOSTS` → deploy fails health gate |

**Prerequisites:** None — this is the first foundation.
**Estimated effort:** ~1 session (30-60 minutes)

## Open Risks & Assumptions

- Railway's health-check host format may not be documented; the `ALLOWED_HOSTS` env var provides a safety net if the exact host is unknown at plan time.
- The skeleton intentionally has no readiness check with dependency probing — F-02 adds this when Postgres is wired.

## Success Criteria (Summary)

- `uv run uvicorn main:app` starts the app locally without errors
- `curl http://localhost:8000/health` returns `{"status": "ok"}` with HTTP 200
- `uv run pytest tests/ -v` passes
- `railway up` deploys successfully and Railway's health check passes (human-gated)
