---
date: 2026-07-29T12:00:00+02:00
researcher: GitHub Copilot
git_commit: 32d63930655bfbad7ebf8840a2279d1d65c18b37
branch: main
repository: patryk-plonka/azure-oracle
topic: "F-03: Auth scaffold — GitHub OAuth + EULA + Demo license + token hashing + per-request validation"
tags: [research, codebase, authentication, oauth, licensing, fastapi, sqlalchemy, alembic]
status: complete
last_updated: 2026-07-29
last_updated_by: GitHub Copilot
---

# Research: F-03 Auth Scaffold — Token & License Validation

**Date**: 2026-07-29T12:00:00+02:00
**Researcher**: GitHub Copilot
**Git Commit**: 32d63930655bfbad7ebf8840a2279d1d65c18b37
**Branch**: main
**Repository**: patryk-plonka/azure-oracle

## Research Question

What does the codebase currently have, what does the PRD/roadmap contract require,
and what needs to be built for foundation F-03 (`auth-scaffold-token-license`)?
The research spans app structure, DB schema patterns, library dependencies, the
auth contract, and scope boundaries — everything needed before writing a plan.

## Summary

**There is zero auth code in the codebase.** The only route is `GET /health`
(public), the only middleware is `TrustedHostMiddleware`, and there are no user,
token, license, or EULA tables. The app uses SQLAlchemy 2.0 + Alembic for
migrations, FastAPI for routing, and `uv` for dependencies.

F-03 is the largest foundation — it delivers the auth scaffold that S-01's
protected search endpoint and S-02's onboarding flow both depend on. The PRD
makes every auth requirement must-have, and the `quality` main_goal requires
per-request (not cached) license validation.

**Key decisions from this research:**
- Only one dependency change needed: promote `httpx` from dev to prod deps
- Unlock at least three open questions deferred to user in the plan
- F-03 can reuse stdlib `secrets` + `hashlib` for token hashing (scaffold-grade),
  with bcrypt upgrade path documented for post-MVP

## Detailed Findings

### 1. Current App Structure — What Exists

The app is a single-file FastAPI service in [`main.py`](https://github.com/patryk-plonka/azure-oracle/blob/32d63930655bfbad7ebf8840a2279d1d65c18b37/main.py#L1-L18):

| Aspect | State | Detail |
|--------|-------|--------|
| Routes | 1 | `GET /health` → `{"status": "ok"}` (line 17) |
| Middleware | 1 | `TrustedHostMiddleware` (line 14), configured from `ALLOWED_HOSTS` env var |
| `Depends()` | 0 | No dependency injection used anywhere |
| Routers | 0 | No `APIRouter` or `app.include_router()` |
| Auth code | 0 | No OAuth, token, license, or user code — not even stubs |

Test pattern ([`tests/test_health.py`](https://github.com/patryk-plonka/azure-oracle/blob/32d63930655bfbad7ebf8840a2279d1d65c18b37/tests/test_health.py#L1-L10)):
```python
from fastapi.testclient import TestClient
from main import app

client = TestClient(app, base_url="http://localhost")
response = client.get("/health")
assert response.status_code == 200
```

The `base_url="http://localhost"` is necessary to satisfy `TrustedHostMiddleware`.
Auth tests will use the same `TestClient` pattern but will need additional
fixtures for tokens and DB state.

### 2. Database & Migration Patterns — What to Replicate

**SQLAlchemy models** ([`models.py`](https://github.com/patryk-plonka/azure-oracle/blob/32d63930655bfbad7ebf8840a2279d1d65c18b37/models.py#L1-L57)):
- `Base = DeclarativeBase` — no custom mixins
- `Mapped[UUID]` + `default=uuid4` for UUID PKs (Python-side generation, native Postgres `UUID` type)
- `Mapped[str | None]` for optional columns
- `__table_args__` tuple for check constraints: `CheckConstraint("btrim(col) <> ''", name="ck_...")`
- Relationships use `back_populates` (never `backref`): `Source.limitations ↔ Limitation.source`
- FK on child: `Mapped[UUID] = mapped_column(ForeignKey("sources.id"), nullable=False)`

**Alembic migrations** ([`migrations/versions/20260729_01_create_sources_and_limitations.py`](https://github.com/patryk-plonka/azure-oracle/blob/32d63930655bfbad7ebf8840a2279d1d65c18b37/migrations/versions/20260729_01_create_sources_and_limitations.py)):
- Procedural `op.create_table()` with `sa.Column()` — not BatchOperations
- Constraints inline: `sa.PrimaryKeyConstraint`, `sa.UniqueConstraint`, `sa.CheckConstraint`, `sa.ForeignKeyConstraint`
- Separate `op.create_index()` calls after table creation
- `server_default=sa.text("CURRENT_TIMESTAMP")` for timestamp columns
- `downgrade()`: drop indexes first, then child tables, then parent tables

**Session/engine** ([`database.py`](https://github.com/patryk-plonka/azure-oracle/blob/32d63930655bfbad7ebf8840a2279d1d65c18b37/database.py#L1-L40)):
- `get_database_url()` validates PostgreSQL, auto-upgrades `postgresql` → `postgresql+psycopg`
- `create_database_engine()` uses `pool_pre_ping=True`
- `sessionmaker(..., expire_on_commit=False)` — attributes stay accessible after commit

**Test DB** ([`tests/conftest.py`](https://github.com/patryk-plonka/azure-oracle/blob/32d63930655bfbad7ebf8840a2279d1d65c18b37/tests/conftest.py#L1-L32)):
- Separate `TEST_DATABASE_URL` env var
- Session-scoped engine with Alembic migrations run programmatically to `head`
- Per-test `TRUNCATE limitations, sources` cleanup (FK order: children first)

### 3. Library Dependencies — What to Add

| Concern | Already Available | New Dependency Needed? | Recommendation |
|---------|-------------------|------------------------|----------------|
| GitHub OAuth | `httpx>=0.27.0` in dev deps | No — promote `httpx` to prod | Three HTTPX calls: code exchange → access token → GET /user. No OAuth library needed for a scaffold. |
| Token generation | `secrets` (stdlib) | No | `secrets.token_urlsafe(32)` — cryptographically random, URL-safe. |
| Token hashing | `hashlib` (stdlib) | No | `hashlib.sha256(token + salt).hexdigest()` for scaffold. Upgrade path to `passlib[bcrypt]` documented for post-MVP. |
| Session cookies | `itsdangerous` (transitive via Starlette) | No | Starlette's `SessionMiddleware` uses `itsdangerous` for signed cookies. Already installed. |

**Action**: Exactly one change to `pyproject.toml` — move `httpx` from `[dependency-groups].dev` to `[project].dependencies`. Zero new packages.

### 4. Auth Contract — The "Done" Definition

From PRD FR-001 through FR-006, roadmap F-03, and the Phase 2 test-plan research
([research.md](https://github.com/patryk-plonka/azure-oracle/blob/32d63930655bfbad7ebf8840a2279d1d65c18b37/context/changes/testing-auth-license-gate/research.md#L1-L97)):

#### Routes F-03 Must Deliver

| Route | Purpose |
|-------|---------|
| `GET /auth/login` | Redirect to GitHub OAuth authorize URL |
| `GET /auth/callback` | Handle OAuth callback: exchange code, fetch user identity, create/update user, set session |
| `GET /auth/token` | Generate API token (requires session + EULA + active license) |
| `POST /auth/token/expire` | Expire a specific token (requires session) |
| `GET /auth/probe` | Minimal protected route for Phase 2 test verification (returns `{"authenticated": true}`) |

#### Models/Tables F-03 Must Create

| Table | Key columns | Notes |
|-------|------------|-------|
| `users` | `id` (UUID PK), `github_id` (unique), `login`, `created_at` | GitHub identity anchor |
| `licenses` | `id` (UUID PK), `user_id` (FK), `license_type`, `is_active`, `created_at` | **Mutable**: `is_active` can change mid-token-life |
| `tokens` | `id` (UUID PK), `user_id` (FK), `token_hash` (unique), `name`, `created_at`, `expires_at` | Hash-only: raw token never stored |

> Note: The [Phase 2 research](https://github.com/patryk-plonka/azure-oracle/blob/32d63930655bfbad7ebf8840a2279d1d65c18b37/context/changes/testing-auth-license-gate/research.md#L92-L94) flagged "token and license schema not defined yet" as an open question.
> This research refines that: `EulaAcceptance` can be a boolean `eula_accepted_at` timestamp on the `users` table — a full separate table is premature for a scaffold with one EULA version.
> The plan should **unlock** this and let the user pick between a separate table vs an inline column.

#### Per-Request Validation Dependency (FR-006)

A single FastAPI `Depends()` that runs before every protected route handler:
1. Extract token from `Authorization: Bearer <token>` header
2. Hash it, look up in `tokens` table
3. Verify not expired
4. Look up associated user's license, verify `is_active = true`
5. If any step fails → reject before the handler runs

**Per-request (not cached)**: FR-006 resolves this explicitly — "license state can
change mid-token-life (expiry/revocation), so it must be checked per request."
The discriminating regression test: mutate the license fixture between two
requests with the same valid token, assert the second request is rejected.

#### Sequential Gate: OAuth → EULA → License → Token

The PRD mandates this ordering (FR-002 → FR-003 → FR-004):

1. User authenticates via GitHub OAuth → session established
2. User accepts EULA → recorded (timestamp on user record or separate table)
3. Demo license assigned → `is_active = true`
4. Token generation unlocked → user can call `GET /auth/token`

No token before EULA. No license before EULA. F-03 must enforce this chain.

### 5. Access-Control Contract (Test Oracle)

From [PRD §Access Control](https://github.com/patryk-plonka/azure-oracle/blob/32d63930655bfbad7ebf8840a2279d1d65c18b37/context/foundation/prd.md#L169-L189) and [Phase 2 research](https://github.com/patryk-plonka/azure-oracle/blob/32d63930655bfbad7ebf8840a2279d1d65c18b37/context/changes/testing-auth-license-gate/research.md#L64-L73):

| Scenario | Required Outcome | Suggested HTTP Status |
|----------|-----------------|----------------------|
| No token | Reject before handler | 401 Unauthorized |
| Expired token | Reject before handler | 401 Unauthorized |
| Active token, inactive license | Reject before handler | 403 Forbidden |
| Active token, active license | Handler runs | 200 OK |
| License deactivated between requests | Second request rejected (no caching) | 403 Forbidden |

> **Open question**: The PRD requires rejection but never specifies HTTP status
> codes. The plan should **unlock** 401/403 as the suggested convention.

### 6. Environment Variables & Secrets

From [deploy-plan.md §3](https://github.com/patryk-plonka/azure-oracle/blob/32d63930655bfbad7ebf8840a2279d1d65c18b37/context/deployment/deploy-plan.md#L60-L75):

| Variable | Purpose | Status |
|----------|---------|--------|
| `GITHUB_OAUTH_CLIENT_ID` | OAuth app client ID | Already declared in deploy-plan |
| `GITHUB_OAUTH_CLIENT_SECRET` | OAuth app client secret | Already declared in deploy-plan |
| `TOKEN_HASH_SALT` | Salt for API token hashing | Already declared in deploy-plan |
| `DATABASE_URL` | Neon Postgres connection | Already configured (F-02) |
| `SECRET_KEY` | Signs Starlette session cookies | **Missing from deploy-plan** — must be added |
| `APP_URL` | Base URL for constructing OAuth callback | **Missing from deploy-plan** — must be added |

> **Open question**: `SECRET_KEY` and `APP_URL` are missing from the deploy-plan
> secrets table. The plan should **unlock** whether to add them to the deploy-plan
> now or handle them separately.

### 7. Scope Boundaries — What F-03 Does NOT Do

**Deferred to S-02 (developer-onboarding-token):**
- OAuth login UI/page (F-03 provides the backend routes only)
- EULA display page (F-03 records acceptance, doesn't render the EULA)
- "Generate token" button/UI (F-03 provides the endpoint)
- Any HTML templates or front-end rendering

Per [roadmap F-03 risk note](https://github.com/patryk-plonka/azure-oracle/blob/32d63930655bfbad7ebf8840a2279d1d65c18b37/context/foundation/roadmap.md#L124): "It is NOT 'the auth layer complete' — S-02 still exercises OAuth + EULA + license + token issuance through a real user-visible onboarding flow."

**Parked (not in F-03):**
- FR-005b: token revocation (nice-to-have, v1.1)
- Full audit trail (FR-015, nice-to-have, v1.1)
- Non-GitHub identity providers (v2)

**Owned by other foundations:**
- F-04: secret-stripping middleware (F-03 should still avoid logging raw tokens)
- S-01: protected REST search endpoint (F-03 provides the gate, not the search)

## Architecture Insights

1. **Auth as `Depends()`, not blanket middleware.** `TrustedHostMiddleware` already
   sits at the HTTP boundary. The token+license check should be a `Depends()`
   attached to protected routes — this keeps `/health`, `/auth/login`, and
   `/auth/callback` unauthenticated while protecting data routes.

2. **Middleware ordering:** `TrustedHostMiddleware` → `SessionMiddleware` →
   (route layer with `Depends()`). Host validation runs first, then session
   cookies are available, then auth dependency runs inside the route.

3. **Single dependency for combined token+license check.** One `Depends()` that
   validates both token validity and license state — not two separate
   dependencies. This keeps the "reject before data" rule at a single boundary.

4. **Separate authentication from authorization in test fixtures.** A valid token
   fixture must be able to pair with an inactive license fixture for the
   discriminating regression test. Don't couple them in fixture construction.

5. **Hash-only token storage.** Tests should seed a known raw token and its
   corresponding stored hash; they must never expect a plaintext database token.
   Use `secrets.token_urlsafe(32)` for generation, `hashlib.sha256(token + salt)`
   for hashing.

6. **Session stores only `user_id`.** The Starlette session cookie should hold
   `{"user_id": str(uuid)}`. Don't serialize the full user object — lookup per
   request.

7. **Inline routes, not a router module (for now).** Four routes total — a
   dedicated `routers/auth.py` is clean but premature for a scaffold. Add routes
   directly in `main.py` or a single `auth.py` at the project root. Extract to a
   router later when S-01 adds the search routes.

## Historical Context (from prior changes)

- **[Phase 2 test research](https://github.com/patryk-plonka/azure-oracle/blob/32d63930655bfbad7ebf8840a2279d1d65c18b37/context/changes/testing-auth-license-gate/research.md#L1-L97)**:
  Established the test oracle for Risk #3 (token+license access control). No
  auth code existed at time of research; this research confirms nothing has
  changed. The Phase 2 research's open questions about HTTP status codes and
  schema design are still open and should be resolved in the F-03 plan.

- **[Deploy skeleton change](https://github.com/patryk-plonka/azure-oracle/blob/32d63930655bfbad7ebf8840a2279d1d65c18b37/context/changes/deploy-skeleton-health/change.md#L1-L16)**:
  Deliberately contains no authentication surface — only the health endpoint and
  host allow-list. F-03 is the first component to add auth.

- **[Postgres schema seed change](https://github.com/patryk-plonka/azure-oracle/blob/32d63930655bfbad7ebf8840a2279d1d65c18b37/context/changes/postgres-schema-seed/)**:
  Delivered the DB connection, migration tooling, and seed import patterns. F-03
  reuses these for user/token/license tables.

- **[Deploy plan secrets](https://github.com/patryk-plonka/azure-oracle/blob/32d63930655bfbad7ebf8840a2279d1d65c18b37/context/deployment/deploy-plan.md#L60-L75)**:
  Already reserves `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`,
  `TOKEN_HASH_SALT`, and `DATABASE_URL` as Railway secrets. `SECRET_KEY` and
  `APP_URL` are not yet in the table.

## Related Research

- [`context/changes/testing-auth-license-gate/research.md`](https://github.com/patryk-plonka/azure-oracle/blob/32d63930655bfbad7ebf8840a2279d1d65c18b37/context/changes/testing-auth-license-gate/research.md) — Phase 2 test-plan research on Risk #3 (token and Demo-license access control), used as prior evidence for the auth contract in this document.

## Open Questions

1. **HTTP status codes for auth rejection** — The PRD requires rejection but
   never specifies codes. Suggested: 401 for missing/expired token, 403 for
   inactive license. Resolve during planning.

2. **EULA tracking: separate table vs inline column** — A `eula_accepted_at`
   timestamp on `users` is simpler; a separate `eula_acceptances` table supports
   multi-version EULAs. Resolve during planning.

3. **`SECRET_KEY` and `APP_URL` in deploy-plan** — Both are needed for F-03
   (`SessionMiddleware` signing key, OAuth callback URL construction) but are
   missing from `deploy-plan.md` §3. Resolve during planning.

4. **Token hashing: SHA-256 now, bcrypt later** — SHA-256 + salt is fine for a
   demo scaffold. The plan should document the post-MVP upgrade path to
   `passlib[bcrypt]`. Resolve during planning (confirm with user).

5. **No auth code in the codebase** — The Phase 2 test research assumed no auth
   code existed; this research confirms that's still true as of commit
   `32d6393`. The F-03 plan starts from a clean slate.
