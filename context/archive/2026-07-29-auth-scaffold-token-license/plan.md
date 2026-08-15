# Auth Scaffold — Token & License Validation — Implementation Plan

## Overview

Build F-03: the auth scaffold that delivers GitHub OAuth login, EULA acceptance
(auto on first login), Demo license assignment, hash-only API token generation
with fixed-TTL expiry, and per-request token+license validation via two chained
`Depends()`. All six PRD must-have FRs (FR-001–FR-006) in one change, with zero
new packages beyond promoting `httpx` to prod deps.

## Current State Analysis

The codebase has **zero auth** — no users, tokens, licenses, OAuth, or
`Depends()` usage. The only route is `GET /health` (public), the only middleware
is `TrustedHostMiddleware`. The DB has `sources` and `limitations` tables with
established SQLAlchemy 2.0 + Alembic patterns.

### Key Discoveries:

- `main.py:1-18` — single-file FastAPI app, 1 route, 1 middleware, 0 `Depends()`
- `models.py:1-57` — `Base = DeclarativeBase`, `Mapped[UUID]` PKs, `back_populates` relationships
- `migrations/versions/20260729_01_*.py` — procedural `op.create_table()`, separate `op.create_index()`, `downgrade()` implemented
- `database.py:1-40` — `get_database_url()` validates PostgreSQL, `sessionmaker(expire_on_commit=False)`
- `tests/conftest.py:1-32` — `TEST_DATABASE_URL`, session-scoped engine, per-test `TRUNCATE`
- `pyproject.toml` — `httpx>=0.27.0` in dev deps; `itsdangerous` NOT in `uv.lock` (Starlette 1.3.1 dropped it)
- Frame brief settled: HMAC-signed OAuth state, two chained `Depends()`, inline routes, inline EULA column

## Desired End State

A deployed FastAPI app where:
- `GET /auth/login` redirects to GitHub OAuth with an HMAC-signed state parameter
- `GET /auth/callback` exchanges the code, creates/updates a user, auto-accepts EULA, assigns a Demo license, and returns a JSON response with user info
- `GET /auth/token` generates an API token (shown once, stored as SHA-256 hash), gated on a short-lived OAuth token grant, EULA acceptance, and an active license
- `POST /auth/token/expire` expires a token by setting `expires_at` to now
- `GET /auth/probe` returns `{"authenticated": true}` only when a valid token + active license are presented
- Two `Depends()` functions (`get_current_user` → 401, `require_active_license` → 403) are available for S-01 to reuse
- `GET /health` remains public and unchanged

## What We're NOT Doing

- **No UI/HTML** — F-03 is backend-only; S-02 adds the onboarding UI
- **No token revocation** — FR-005b is parked (v1.1)
- **No audit trail** — FR-015 is parked (v1.1); EULA acceptance is recorded as a timestamp column
- **No non-GitHub identity** — v2 concern
- **No secret-stripping middleware** — owned by F-04; F-03 avoids logging raw tokens
- **No `SessionMiddleware`** — frame ruled it out; `itsdangerous` isn't installed
- **No `APIRouter`** — inline routes for the scaffold; extract during S-01

## Implementation Approach

**Zero new packages.** Promote `httpx` to prod deps. Use stdlib `secrets` for
token generation, `hashlib` for hashing, `hmac` for OAuth state signing.

**Two chained `Depends()`** — `get_current_user` (extracts Bearer token, hashes,
looks up, checks expiry → 401) and `require_active_license` (checks user's
license `is_active` → 403). FastAPI executes them in order; the first failure
short-circuits.

**HMAC-signed OAuth state** — `state = nonce + "." + HMAC(SECRET_KEY, nonce)`.
On callback, split, recompute HMAC, compare. No DB storage.

**Auto-accept EULA on first login** — `eula_accepted_at` is set to `now()` when
the user row is first created during OAuth callback. No separate EULA endpoint.

**Fixed TTL token expiry** — 90 days from creation. `POST /auth/token/expire`
sets `expires_at` to `now()` for immediate expiry.

## Phase 1: Data Model — Users, Licenses, Tokens

### Overview

Create the three new SQLAlchemy models and the Alembic migration. This phase
produces the schema that Phases 2–4 read and write.

### Changes Required:

#### 1. Add auth models to `models.py`

**File**: `models.py`

**Intent**: Add `User`, `License`, and `Token` models following the existing
`Base = DeclarativeBase` pattern. `User` has an inline `eula_accepted_at`
timestamp column (not a separate table). `License` is a separate table because
it's mutable and 1:N (a user could have multiple license records over time,
though v1 only has one active Demo license). `Token` stores only the hash.

**Contract**:

- `User`: `id` (UUID PK, default uuid4), `github_id` (Integer, unique, not null), `login` (String(255), not null), `eula_accepted_at` (DateTime(timezone=True), nullable), `created_at` (DateTime(timezone=True), not null, server_default now())
- `License`: `id` (UUID PK, default uuid4), `user_id` (FK → users.id, not null), `license_type` (String(32), not null, default 'demo'), `is_active` (Boolean, not null, default True), `created_at` (DateTime(timezone=True), not null, server_default now())
- `Token`: `id` (UUID PK, default uuid4), `user_id` (FK → users.id, not null), `token_hash` (String(128), not null), `name` (String(255), not null), `created_at` (DateTime(timezone=True), not null, server_default now()), `expires_at` (DateTime(timezone=True), not null)
- Relationships: `User.licenses` ↔ `License.user` (back_populates), `User.tokens` ↔ `Token.user` (back_populates)
- Index on `Token.token_hash` (unique), index on `License.user_id`

#### 2. Create Alembic migration

**File**: `migrations/versions/20260729_02_create_users_licenses_tokens.py`

**Intent**: Create the three tables following the existing migration pattern
(procedural `op.create_table()`, separate `op.create_index()`, full `downgrade()`).

**Contract**:
- `down_revision: str | None = "20260729_01"`
- `upgrade()`: create `users` → `licenses` → `tokens` in FK order, then indexes
- `downgrade()`: drop indexes → `tokens` → `licenses` → `users`
- `server_default=sa.text("CURRENT_TIMESTAMP")` for `created_at` columns
- `server_default=sa.text("'demo'")` for `license_type`
- `server_default=sa.text("true")` for `is_active`

#### 3. Update `tests/conftest.py` TRUNCATE list

**File**: `tests/conftest.py`

**Intent**: Add the new tables to the per-test cleanup so auth tests start with a clean slate.

**Contract**: Extend the `TRUNCATE` statement to include `tokens, licenses, users` (FK order: children first).

### Success Criteria:

#### Automated Verification:

- Migration applies cleanly: `uv run alembic upgrade head`
- Migration downgrades cleanly: `uv run alembic downgrade 20260729_01`
- Existing tests still pass: `uv run pytest tests/ -v`
- Type checking passes: `uv run mypy models.py`

#### Manual Verification:

- Inspect the migrated DB — `users`, `licenses`, `tokens` tables exist with correct columns and constraints

---

## Phase 2: OAuth Flow — Login, Callback, User Creation

### Overview

Implement GitHub OAuth login redirect and callback. On callback: exchange the
code for an access token, fetch the GitHub user identity, create or update the
local user row (auto-accepting EULA on first creation), assign a Demo license
if none exists, and return a JSON response.

### Changes Required:

#### 1. Promote `httpx` to production dependencies

**File**: `pyproject.toml`

**Intent**: Move `httpx` from `[dependency-groups].dev` to `[project].dependencies`
so it's available at runtime for GitHub API calls.

**Contract**: Add `"httpx>=0.27.0"` to `[project].dependencies`, remove from `[dependency-groups].dev`.

#### 2. Add `SECRET_KEY` and `APP_URL` environment variable handling

**File**: `main.py`

**Intent**: Read `SECRET_KEY` (for HMAC signing) and `APP_URL` (for OAuth redirect
URI construction) from environment. Fail fast at startup if either is missing,
since OAuth routes cannot function without them.

**Contract**: At module level, read `os.getenv("SECRET_KEY")` and `os.getenv("APP_URL")`. Raise a clear error if absent.

#### 3. Add `GET /auth/login` route

**File**: `main.py`

**Intent**: Generate an HMAC-signed state parameter, build the GitHub OAuth
authorize URL, and return a 302 redirect.

**Contract**:
- Generate `nonce = secrets.token_urlsafe(16)`
- Compute `signature = hmac.new(SECRET_KEY.encode(), nonce.encode(), hashlib.sha256).hexdigest()[:32]`
- `state = f"{nonce}.{signature}"`
- Redirect to `https://github.com/login/oauth/authorize?client_id={GITHUB_OAUTH_CLIENT_ID}&redirect_uri={APP_URL}/auth/callback&state={state}&scope=read:user`

#### 4. Add `GET /auth/callback` route

**File**: `main.py`

**Intent**: Verify the HMAC state, exchange the OAuth code for an access token,
fetch the GitHub user identity, create or update the local user, auto-accept
EULA on first creation, assign a Demo license if none exists, and return JSON.

**Contract**:
- Verify state: split on `.`, recompute HMAC, compare signatures (constant-time). Reject with 400 if invalid.
- Exchange code: `POST https://github.com/login/oauth/access_token` with `client_id`, `client_secret`, `code`. Parse `access_token` from response.
- Fetch user: `GET https://api.github.com/user` with `Authorization: Bearer {access_token}`. Extract `id` (github_id) and `login`.
- Upsert user: `INSERT ... ON CONFLICT (github_id) DO UPDATE SET login = ...`. On insert, set `eula_accepted_at = now()` (auto-accept).
- Ensure license: if no active Demo license exists for this user, insert one with `license_type='demo'`, `is_active=True`.
- Return JSON: `{"user_id": "...", "login": "...", "eula_accepted": true, "license": "demo", "token_grant": "..."}`, where `token_grant` is a five-minute HMAC-signed bearer grant for token issuance.

### Success Criteria:

#### Automated Verification:

- `GET /auth/login` returns 302 with `Location` header pointing to `github.com`
- `GET /auth/callback?state=invalid` returns 400
- `GET /auth/callback?code=fake&state=valid_sig` returns 400 (bad code)
- Type checking and linting pass

#### Manual Verification:

- With real GitHub OAuth credentials, visiting `/auth/login` in a browser redirects to GitHub, authorizing returns JSON with user info
- Second login for the same GitHub user returns the same user (upsert, not duplicate)

---

## Phase 3: Token Generation & Expiration

### Overview

Add `GET /auth/token` (generate a hash-only API token, gated on a short-lived
OAuth token grant, EULA, and active license) and `POST /auth/token/expire`
(expire a token). Token generation uses `secrets.token_urlsafe(32)`, stores
only `SHA-256(token + TOKEN_HASH_SALT)`, and sets `expires_at = now() + 90
days`.

### Changes Required:

#### 1. Add `GET /auth/token` route

**File**: `main.py`

**Intent**: Generate an API token for the authenticated user. Gate on EULA
acceptance and active Demo license. Return the raw token exactly once.

**Contract**:

- The OAuth callback returns user info but doesn't establish a persistent session. It also returns a five-minute token grant containing a user ID, expiry, and HMAC signature. `GET /auth/token` accepts the grant as `?grant=<user_id>.<expires_at>.<hmac>`.
- Verify the grant's HMAC signature and expiry. Look up user. Verify `eula_accepted_at` is not null (400 if not). Verify user has an active license (403 if not).
- Generate `raw = secrets.token_urlsafe(32)`, compute `token_hash = hashlib.sha256((raw + TOKEN_HASH_SALT).encode()).hexdigest()`.
- Insert into `tokens` table with `expires_at = now() + timedelta(days=90)`.
- Return JSON: `{"token": raw, "expires_at": "...", "name": "default"}`. The raw token is returned once and never stored.

#### 2. Add `POST /auth/token/expire` route

**File**: `main.py`

**Intent**: Expire a specific token by setting its `expires_at` to now. Accepts
the existing HMAC-signed `user_id` authorization used for operator-managed
expiration.

**Contract**:
- Accept JSON body: `{"token_hash": "..."}` or `{"token": "raw_token"}` (hash it server-side).
- Verify the HMAC-signed user ID and that the token belongs to that user.
- Set `token.expires_at = now()` (UTC).
- Return `{"expired": true}`.

#### 3. Add `TOKEN_HASH_SALT` environment variable handling

**File**: `main.py`

**Intent**: Read `TOKEN_HASH_SALT` from environment. Fail fast if missing.

**Contract**: At module level, read `os.getenv("TOKEN_HASH_SALT")`. Raise a clear error if absent.

### Success Criteria:

#### Automated Verification:

- `GET /auth/token` with a valid, unexpired OAuth token grant returns a token string
- `GET /auth/token` with user who hasn't accepted EULA returns 400
- `GET /auth/token` with user who has no active license returns 403
- `POST /auth/token/expire` sets `expires_at` to now; subsequent probe with that token returns 401
- Generated token is not stored in plaintext (verify DB contains only hash)
- Type checking and linting pass

#### Manual Verification:

- Generate a token, copy it, use it in Phase 4's probe route — it works
- Expire the token, use it again — it's rejected

---

## Phase 4: Per-Request Validation Dependencies

### Overview

Implement the two chained `Depends()` functions that S-01 will reuse:
`get_current_user` (extracts Bearer token, hashes, looks up, checks expiry →
401) and `require_active_license` (checks user's license `is_active` → 403).
Add the `/auth/probe` route to verify the full chain.

### Changes Required:

#### 1. Create `auth.py` module with dependencies

**File**: `auth.py` (new file at project root)

**Intent**: Extract the two `Depends()` functions into a reusable module. This
is the contract S-01 and S-03 will import. The module also contains the shared
token hashing function.

**Contract**:

- `hash_token(raw: str) -> str`: `hashlib.sha256((raw + TOKEN_HASH_SALT).encode()).hexdigest()`
- `get_current_user(authorization: str = Header(None)) -> User`: extract `Bearer <token>`, hash, query `tokens` table joined with `users`, verify `expires_at > now()`. Raise `HTTPException(401)` on any failure. Return the `User` ORM object.
- `require_active_license(user: User = Depends(get_current_user)) -> User`: query `licenses` table for `user_id` with `is_active == True`. Raise `HTTPException(403)` if none found. Return the `User` (pass-through for handler use).
- Uses `create_session_factory()` from `database.py` to get a DB session per request.

#### 2. Add `GET /auth/probe` route

**File**: `main.py`

**Intent**: A minimal protected route that exercises both dependencies. Returns
`{"authenticated": true}` when a valid token + active license are presented.

**Contract**:
- `@app.get("/auth/probe")`
- `def probe(user: User = Depends(require_active_license)): return {"authenticated": True, "user": user.login}`
- This chains both dependencies: `require_active_license` depends on `get_current_user`, which depends on the `Authorization` header.

### Success Criteria:

#### Automated Verification:

- `GET /auth/probe` with no token → 401
- `GET /auth/probe` with expired token → 401
- `GET /auth/probe` with valid token but inactive license → 403
- `GET /auth/probe` with valid token + active license → 200, `{"authenticated": true, "user": "..."}`
- Type checking and linting pass

#### Manual Verification:

- Generate a token in Phase 3, use it against `/auth/probe` — 200
- Manually deactivate the license in DB, retry — 403
- Reactivate the license, retry — 200 (proves per-request, not cached)

---

## Phase 5: Wiring, Tests & Verification

### Overview

Wire everything into `main.py`, add unit tests for the `Depends()` functions,
add integration tests for the probe route, update `pyproject.toml` and
`uv.lock`, and verify the full contract.

### Changes Required:

#### 1. Wire all routes and dependencies into `main.py`

**File**: `main.py`

**Intent**: Import and register all auth routes and the `auth.py` module.
Ensure middleware ordering is correct: `TrustedHostMiddleware` runs first,
then routes with `Depends()` handle auth at the route layer.

**Contract**:
- Import `get_current_user`, `require_active_license`, `hash_token` from `auth`
- Import `User`, `License`, `Token` from `models`
- Import `create_session_factory` from `database`
- All routes from Phases 2–4 are registered on the `app` object
- `SECRET_KEY`, `APP_URL`, `TOKEN_HASH_SALT`, `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET` read from env at module level

#### 2. Add unit tests for `Depends()` functions

**File**: `tests/test_auth_dependencies.py` (new file)

**Intent**: Test `get_current_user` and `require_active_license` in isolation
using seeded DB fixtures. Cover all scenarios from the test oracle.

**Contract**:
- Fixture: seed a user with an active license and a valid token (known raw + stored hash)
- `test_get_current_user_no_header` → 401
- `test_get_current_user_expired_token` → 401
- `test_get_current_user_valid_token` → returns User
- `test_require_active_license_inactive` → 403
- `test_require_active_license_active` → returns User
- `test_license_deactivated_between_requests` → first call 200, mutate license, second call 403

#### 3. Add integration tests for `/auth/probe`

**File**: `tests/test_auth_probe.py` (new file)

**Intent**: Test the full middleware + Depends chain through TestClient.

**Contract**:
- `test_probe_no_token` → 401
- `test_probe_expired_token` → 401
- `test_probe_inactive_license` → 403
- `test_probe_valid` → 200

#### 4. Update `pyproject.toml` and lock file

**File**: `pyproject.toml`, `uv.lock`

**Intent**: Promote `httpx` to prod deps and regenerate the lock file.

**Contract**: Run `uv lock` after editing `pyproject.toml`.

### Success Criteria:

#### Automated Verification:

- All existing tests pass: `uv run pytest tests/ -v`
- All new auth tests pass: `uv run pytest tests/test_auth_dependencies.py tests/test_auth_probe.py tests/test_auth_token.py -v`
- Type checking passes: `uv run mypy main.py auth.py models.py`
- Linting passes: `uv run ruff check .`

#### Manual Verification:

- Start the app with all required env vars: `uv run uvicorn main:app`
- `GET /health` → 200 (unchanged)
- `GET /auth/login` → 302 redirect to GitHub
- `GET /auth/probe` without token → 401
- Full OAuth flow with real GitHub credentials → token generated → probe returns 200

---

## Testing Strategy

### Unit Tests (`tests/test_auth_dependencies.py`):

- `get_current_user`: no header, malformed header, expired token, valid token
- `require_active_license`: active license, inactive license, no license
- Discriminating regression: license deactivated between two requests with same token
- `hash_token`: deterministic output for same input, different output for different salt

### Integration Tests (`tests/test_auth_probe.py`):

- Full TestClient chain: TrustedHostMiddleware → route → Depends() → handler
- All 5 scenarios from the test oracle

### Manual Testing Steps:

1. Set all required env vars (`SECRET_KEY`, `APP_URL`, `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`, `TOKEN_HASH_SALT`, `DATABASE_URL`, `ALLOWED_HOSTS`)
2. Run migrations: `uv run alembic upgrade head`
3. Start server: `uv run uvicorn main:app`
4. Visit `/auth/login` in browser → authorize on GitHub → see JSON response
5. Generate token: use the callback's `token_grant` with `GET /auth/token?grant=...` → copy token
6. Probe: `curl -H "Authorization: Bearer <token>" /auth/probe` → 200
7. Expire token: `POST /auth/token/expire` → probe again → 401

## Performance Considerations

- Token lookup is by hash (indexed, unique) — O(1) per request
- License check is by user_id (indexed) — O(1) per request
- No session state — fully stateless after OAuth callback
- GitHub API calls only happen during OAuth callback (login), not on every request

## Migration Notes

- Migration `20260729_02` depends on `20260729_01` (the sources + limitations tables)
- `downgrade()` is implemented for all migrations
- No data migration needed — new tables only
- Existing `TRUNCATE` in `conftest.py` must be updated to include new tables

## References

- Research: `context/changes/auth-scaffold-token-license/research.md`
- Frame brief: `context/changes/auth-scaffold-token-license/frame.md`
- Prior research: `context/changes/testing-auth-license-gate/research.md`
- PRD: `context/foundation/prd.md` §FR-001–FR-006, §Access Control
- Test plan: `context/foundation/test-plan.md` Risk #3, Phase 2
- Roadmap: `context/foundation/roadmap.md` F-03
- Deploy plan: `context/deployment/deploy-plan.md` §3 Secrets
- Existing migration: `migrations/versions/20260729_01_create_sources_and_limitations.py`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Data Model — Users, Licenses, Tokens

#### Automated

- [x] 1.1 Migration applies cleanly: `uv run alembic upgrade head` — e7573f8
- [x] 1.2 Migration downgrades cleanly: `uv run alembic downgrade 20260729_01` — e7573f8
- [x] 1.3 Existing tests still pass: `uv run pytest tests/ -v` — e7573f8
- [x] 1.4 Type checking passes: `uv run mypy models.py` — e7573f8

#### Manual

- [x] 1.5 Inspect migrated DB — tables exist with correct columns and constraints

### Phase 2: OAuth Flow — Login, Callback, User Creation

#### Automated

- [x] 2.1 `GET /auth/login` returns 302 with `Location` pointing to github.com — 5e0a0d5
- [x] 2.2 `GET /auth/callback?state=invalid` returns 400 — 5e0a0d5
- [x] 2.3 Type checking and linting pass — 5e0a0d5

#### Manual

- [x] 2.4 Real GitHub OAuth login flow works end-to-end on Railway — 5e0a0d5

### Phase 3: Token Generation & Expiration

#### Automated

- [x] 3.1 `GET /auth/token` with valid HMAC-signed user_id returns a token
- [x] 3.2 `GET /auth/token` without EULA returns 400
- [x] 3.3 `GET /auth/token` without active license returns 403
- [x] 3.4 `POST /auth/token/expire` expires token; subsequent probe returns 401
- [x] 3.5 Generated token not stored in plaintext (verify DB)
- [x] 3.6 Type checking and linting pass — 70c0846

#### Manual

- [x] 3.7 Generate token, use against probe — works; expire, retry — rejected

### Phase 4: Per-Request Validation Dependencies

#### Automated

- [x] 4.1 `GET /auth/probe` no token → 401
- [x] 4.2 `GET /auth/probe` expired token → 401
- [x] 4.3 `GET /auth/probe` valid token, inactive license → 403
- [x] 4.4 `GET /auth/probe` valid token, active license → 200
- [x] 4.5 Type checking and linting pass — 3953f6f

#### Manual

- [x] 4.6 Deactivate license in DB mid-session, retry probe → 403 (proves per-request)

### Phase 5: Wiring, Tests & Verification

#### Automated

- [x] 5.1 All existing tests pass: `uv run pytest tests/ -v`
- [x] 5.2 All new auth tests pass: `uv run pytest tests/test_auth_dependencies.py tests/test_auth_probe.py tests/test_auth_token.py -v`
- [x] 5.3 Type checking passes: `uv run mypy main.py auth.py models.py` — 6be0585
- [x] 5.4 Linting passes: `uv run ruff check .` — 6be0585

#### Manual

- [x] 5.5 Full manual walkthrough: health → login → token → probe → expire → probe rejected