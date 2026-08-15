# Auth Scaffold — Token & License Validation — Plan Brief

> Full plan: `context/changes/auth-scaffold-token-license/plan.md`
> Frame brief: `context/changes/auth-scaffold-token-license/frame.md`
> Research: `context/changes/auth-scaffold-token-license/research.md`

## What & Why

> **The actual problem**: F-03 is the right scope (one change, all six FRs),
> but three architectural decisions in the research need correction. Build the
> auth scaffold — GitHub OAuth, EULA acceptance, Demo license, hash-only API
> tokens, and per-request token+license validation — as the gate S-01's
> protected search endpoint depends on, with zero new packages.

## Starting Point

The codebase has **zero auth** — one public route (`GET /health`), one
middleware (`TrustedHostMiddleware`), no `Depends()` usage. F-01 (deploy
skeleton) and F-02 (Postgres + schema + seed) are done. The DB has
`sources` and `limitations` tables with established SQLAlchemy 2.0 + Alembic
patterns. `httpx` is in dev deps; `itsdangerous` is **not** installed
(Starlette 1.3.1 dropped it as a hard dependency).

## Desired End State

A deployed FastAPI app where a user can log in via GitHub OAuth, have a Demo
license auto-assigned, generate a hash-only API token, and use that token
against protected endpoints. Two chained `Depends()` functions
(`get_current_user` → 401, `require_active_license` → 403) are available as
the reusable auth contract for S-01 and S-03.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Auth enforcement pattern | `Depends()`, not middleware | Keeps `/health` and OAuth routes public; `BaseHTTPMiddleware` has known `TestClient` issues | Frame |
| Token+license coupling | Two chained `Depends()` (401/403) | PRD says "unauthenticated **or** unlicensed"; discriminating regression test is easier with distinct status codes | Frame |
| Session strategy | HMAC-signed form field, not `SessionMiddleware` | `itsdangerous` isn't installed; HMAC uses stdlib only, preserving zero new packages | Frame |
| EULA tracking | Inline `eula_accepted_at` column on `users` | PRD has no EULA versioning; separate table is YAGNI | Frame |
| Route organization | Inline routes in `main.py` | 5 routes, ~80 lines — still readable; extract to `APIRouter` during S-01 | Frame |
| EULA acceptance flow | Auto-accept on first OAuth login | Simplest path; EULA is a product gate, not a user-facing step in the scaffold | Plan |
| OAuth CSRF | HMAC-signed state parameter | Zero new deps; self-validating; no DB storage | Plan |
| Token expiry | Fixed 90-day TTL | Simple, matches FR-005; `POST /auth/token/expire` for immediate expiry | Plan |
| Token hashing | SHA-256(salt + token) | Stdlib only; bcrypt upgrade path documented for post-MVP | Research |
| Test strategy | Unit tests for `Depends()` + integration for `/auth/probe` | Covers the auth gate at both levels; OAuth callback is manually tested | Plan |
| Dependencies | Promote `httpx` to prod; zero new packages | GitHub OAuth is 3 HTTPX calls; stdlib covers hashing, HMAC, and secrets | Research |

## Scope

**In scope:**
- GitHub OAuth login + callback with HMAC CSRF protection
- Auto EULA acceptance on first login
- Demo license auto-assignment
- Hash-only API token generation (90-day TTL) and expiration
- Two chained `Depends()` for per-request token+license validation
- `/auth/login`, `/auth/callback`, `/auth/token`, `/auth/token/expire`, `/auth/probe` routes
- Unit + integration tests covering the full test oracle

**Out of scope:**
- UI/HTML (S-02), token revocation (FR-005b, v1.1), audit trail (FR-015, v1.1)
- Non-GitHub identity (v2), secret-stripping middleware (F-04)
- `SessionMiddleware`, `APIRouter` module, separate EULA table

## Architecture / Approach

```
Browser                    FastAPI (main.py)              GitHub API          Postgres
  |                              |                            |                  |
  |-- GET /auth/login ---------->|                            |                  |
  |<-- 302 github.com/authorize  |                            |                  |
  |                              |                            |                  |
  |-- GET /auth/callback?code=X->|                            |                  |
  |                              |-- POST /access_token ----->|                  |
  |                              |<-- access_token ----------|                  |
  |                              |-- GET /user -------------->|                  |
  |                              |<-- {id, login} -----------|                  |
  |                              |                            |  UPSERT users    |
  |                              |                            |  INSERT license  |
  |<-- {"user_id", "login"} -----|                            |                  |
  |                              |                            |                  |
  |-- GET /auth/token?uid=&sig=->|                            |                  |
  |                              |  (verify HMAC, check EULA) |                  |
  |                              |  (generate token, hash)    |  INSERT tokens   |
  |<-- {"token": "raw_..."} -----|                            |                  |
  |                              |                            |                  |
  |-- GET /auth/probe ---------->|                            |                  |
  |   Authorization: Bearer raw  |                            |                  |
  |                              |  Depends(get_current_user) |  SELECT tokens   |
  |                              |  Depends(require_license)  |  SELECT licenses |
  |<-- {"authenticated": true} --|                            |                  |
```

Per-request validation is stateless: extract Bearer token → hash → DB lookup →
check expiry → check license active. No session, no cache.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Data Model | Users, licenses, tokens tables + migration | FK ordering in migration; TRUNCATE list update in conftest |
| 2. OAuth Flow | Login redirect + callback + user creation | GitHub API changes; callback URL mismatch between APP_URL and GitHub app settings |
| 3. Token Generation | Hash-only token creation (90-day TTL) + expiration | HMAC-signed user_id auth for /auth/token is a non-standard pattern; document clearly for S-02 |
| 4. Validation Dependencies | Two chained Depends() + /auth/probe | Depends() ordering — license must depend on user to chain correctly |
| 5. Tests & Verification | Unit tests + integration tests + full walkthrough | Test DB needs all env vars; OAuth callback is manual-only |

**Prerequisites:** F-01 (deploy skeleton), F-02 (Postgres + schema) — both done. `SECRET_KEY`, `APP_URL`, `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET` env vars set.
**Estimated effort:** ~2-3 sessions across 5 phases

## Open Risks & Assumptions

- **HMAC-signed user_id for `/auth/token` is unusual.** The scaffold has no session, so token generation needs an auth mechanism. The HMAC-signed query parameter is the simplest path. S-02 will replace this with a proper session-based flow.
- **OAuth callback can't be integration-tested without a real GitHub app.** Phase 5's manual verification covers this. A CI test with a mock HTTPX transport could be added later.
- **`SECRET_KEY` and `APP_URL` are missing from deploy-plan.** They must be added to Railway secrets before deploy. The plan reads them at startup and fails fast if absent.

## Success Criteria (Summary)

- Protected endpoint rejects: no token (401), expired token (401), inactive license (403)
- Protected endpoint serves: valid token + active license (200)
- License deactivation mid-session takes effect on the next request (no caching)
- Tokens are stored only as hashes; raw token returned once
- All existing tests pass; new auth tests cover the full test oracle