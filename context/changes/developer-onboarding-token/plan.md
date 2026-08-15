# Developer Onboarding Token Implementation Plan

## Overview

Turn the completed auth scaffold into a self-service, API-first onboarding journey. A developer authenticates with GitHub, explicitly reads and accepts versioned Demo terms, receives an active Demo license, creates one named API token that is shown only in its creation response, and can expire any of their tokens by opaque ID.

The implementation replaces scaffold-only handoffs that are not user-completable—automatic consent/license assignment, replayable signed OAuth state and issuance grants, and server-secret HMAC token expiration—with expiring, single-use database-backed lifecycle state. OAuth callback state is isolated in a pre-identity `OAuthState` record; user-owned `AuthGrant` records are reserved for onboarding and issuance. It preserves hash-only token storage, explicit `Depends()` authorization, and secret-safe logging.

## Current State Analysis

The repository has F-03's backend auth foundation and S-01's protected REST search endpoint. `main.py` holds all auth routes inline: GitHub OAuth callback currently auto-sets `User.eula_accepted_at`, creates a Demo license, returns a signed five-minute `token_grant`, and `GET /auth/token` creates a 90-day token. `POST /auth/token/expire` instead requires a `user_id` signature that only the server can derive, so a normal developer cannot use it.

### Key Discoveries:

- `main.py:193-275` verifies a timeless signed OAuth `state`, upserts a user while silently accepting the EULA, creates a Demo license, and returns an issuance grant.
- `main.py:282-373` passes the grant through a query parameter and exposes expiration through an unreachable server-secret HMAC contract.
- `auth.py:36-80` already centralizes valid-token and per-request active-license checks as two chained FastAPI dependencies; this must remain the protected-data boundary.
- `models.py:66-152` and migration `20260806_01` now contain consent, lifecycle-event, and owned-grant state; its original `oauth_state` grant purpose conflicts with the required non-null owner before GitHub identifies a user, so Phase 2 must correct it through a forward migration.
- `logging_middleware.py:43-91` records only method/path/status and never request or response contents, providing the required no-secret logging pattern.
- `context/foundation/test-plan.md` §6.4 calls for deterministic unit/integration auth tests, explicitly excludes GitHub-provider testing, and requires raw tokens to be absent from normal and error logs.
- `context/deployment/deploy-plan.md:67-76` omits runtime-required `SECRET_KEY` and `APP_URL`; `README.md` has no OAuth/onboarding/token operating guide.

## Desired End State

A developer can complete a documented, OpenAPI-compatible onboarding workflow without a dashboard or CLI:

1. Start GitHub OAuth at `GET /auth/login`.
2. Complete the callback and receive a short-lived, single-use onboarding credential that allows the developer to retrieve the current versioned Demo EULA.
3. Explicitly accept that exact EULA version; acceptance is recorded, an active Demo license is assigned transactionally, and an issuance credential is returned.
4. Use the single-use issuance credential to create a named 90-day token. The raw token and its opaque token ID appear only in that successful creation response; the database retains its hash only.
5. Use the token immediately with protected endpoints, or use a valid owned token to expire any token belonging to the same user by opaque ID.

OAuth state, onboarding credentials, and issuance credentials are bounded by a short TTL and are consumed after successful use. Protected API responses continue to require a valid non-expired token and an active `demo` license on every request. Minimal non-secret lifecycle events record EULA acceptance, Demo-license assignment, and token creation.

## What We're NOT Doing

- No web dashboard, HTML consent page, frontend framework, or browser E2E suite.
- No CLI onboarding/configuration client.
- No OAuth providers besides GitHub.
- No token revocation model beyond setting a token's expiry to the current time.
- No raw-token listing, retrieval, persistence, or logging after its creation response.
- No generalized audit UI, audit-query API, administrator role, or retention system; only the three required lifecycle event types are stored.
- No full structured/correlated logging (FR-014), region/SKU filtering, MCP wrapper, or changes to the limitation-query behavior.

## Implementation Approach

Keep the API-first architecture and root-level module convention. Add typed request/response schemas for public onboarding contracts and database-backed, short-lived records for OAuth state and scoped onboarding/issuance credentials. `OAuthState` is deliberately ownerless before identity verification; `AuthGrant` remains user-owned and has only `onboarding` and `token_issuance` purposes. Store only opaque random values as hashes, with expiry and consumed timestamps, so the service can validate and atomically consume bearer handoffs without persisting reusable plaintext credentials.

The OAuth callback is only an identity handoff: it verifies and consumes state, exchanges the code with GitHub, upserts the user, and produces onboarding state. EULA acceptance—not login—records consent and creates an active Demo license. Token issuance requires a consumed-on-success issuance credential. Token expiration uses `require_active_license`, looks up an owned token by ID, and moves only that token's expiry to now. Extend the existing `get_current_user` / `require_active_license` chain to make `license_type == "demo"` an explicit MVP invariant.

## Critical Implementation Details

OAuth state is claimed only after GitHub identity verification and in the same transaction as local user upsert and creation of an owned onboarding grant. EULA acceptance and token issuance likewise consume their owned grant in the same transaction as their state mutation. Use PostgreSQL conditional `UPDATE … RETURNING` claims so concurrent consumers have exactly one winner; never mark a credential consumed in a committed transaction before its downstream transition can commit.

## Phase 1: Persist Consent, Lifecycle, and One-Time Credentials

### Overview

Extend the database model so the service can identify accepted Demo terms, retain the required onboarding events, and issue/consume expiring single-use OAuth and onboarding handoffs without storing their raw values.

### Changes Required:

#### 1. Extend user and auth-lifecycle SQLAlchemy models

**File**: `models.py`

**Intent**: Preserve the existing `User`, `License`, and `Token` relationships while adding the minimum durable state needed for versioned consent, required lifecycle evidence, and replay-resistant owned transient credentials.

**Contract**: Add nullable `User.eula_version` paired with `eula_accepted_at`; add an append-only `LifecycleEvent` entity with UUID ID, user foreign key, constrained event type, non-secret metadata/version context, and server-created timestamp; add an owned `AuthGrant` entity with UUID ID, user foreign key, hashed opaque credential, purpose, expiry, and nullable consumed timestamp. Do not add a raw-token or raw-grant column. Phase 2 corrects the initial over-broad purpose constraint by separating pre-identity OAuth state into its own table; Phase 1 completion remains historical and must not be rewritten.

#### 2. Create the schema migration

**File**: `migrations/versions/<new_revision>_create_onboarding_lifecycle_state.py`

**Intent**: Apply the model delta using the repository's procedural Alembic convention and preserve clean downgrade behavior.

**Contract**: Depend on `20260729_02`; add `eula_version` to `users`; create lifecycle-event and auth-grant tables after `users`; create indexes after tables; downgrade in reverse dependency order. Add a partial unique index on `licenses(user_id) WHERE is_active` so at most one active license per user is DB-enforced (verify no deployed rows violate it before applying; scaffold-era data should be clean). Use server timestamps consistent with existing migrations and constraints that reject blank lifecycle purpose/type values.

#### 3. Refresh database test fixtures

**File**: `tests/conftest.py`

**Intent**: Ensure all tests begin with no users, tokens, licenses, onboarding credentials, or lifecycle events while preserving the isolated `TEST_DATABASE_URL` contract.

**Contract**: Extend the existing child-before-parent `TRUNCATE` statement to include all new auth-lifecycle tables; add focused factories/fixtures for users, Demo and non-Demo license states, short-lived grants, and owned/unowned tokens without embedding secrets in fixture output.

### Success Criteria:

#### Automated Verification:

- The new Alembic revision upgrades an empty test database from `base` to `head`, and the existing migration recreation/seed test still passes: `uv run pytest tests/test_seed_import.py -v`
- The migration upgrades and downgrades cleanly around the new revision: `uv run alembic upgrade head; uv run alembic downgrade 20260729_02; uv run alembic upgrade head`
- Auth fixture cleanup leaves no rows in token, grant, lifecycle-event, license, or user tables between tests: `uv run pytest tests/test_auth_dependencies.py -v`
- Static checks pass for the persistence changes: `uv run ruff check models.py migrations tests/conftest.py; uv run mypy models.py tests/conftest.py`

#### Manual Verification:

- Inspect the migrated schema and confirm EULA version, one-time credential, and lifecycle-event records contain no raw token or raw grant values.
- Verify migration downgrade removes only S-02 schema objects and leaves existing sources, limitations, users, licenses, and tokens intact before re-upgrade.

**Implementation Note**: After completing this phase and all automated verification passes, pause for human confirmation that the schema inspection and downgrade/re-upgrade checks succeeded before proceeding.

---

## Phase 2: Explicit OAuth and EULA Onboarding State Machine

### Overview

Correct the Phase 1 ownership mismatch and replace automatic consent with a secure, self-service OAuth-to-EULA progression. The API stores pre-identity OAuth state separately, issues an owned onboarding credential after GitHub identity verification, exposes versioned repository-owned Demo terms, records explicit consent, assigns the Demo license, and emits the two required lifecycle events.

### Changes Required:

#### 1. Separate pre-identity OAuth state from owned auth grants

**Files**: `models.py`, `migrations/versions/20260807_01_split_oauth_state_from_auth_grants.py` (new), `tests/conftest.py`, `tests/test_auth_dependencies.py`

**Intent**: Repair the applied Phase 1 schema without weakening the invariant that every onboarding or issuance credential belongs to a known user. OAuth state exists before GitHub identity is known and needs its own hash-only, one-time persistence boundary.

**Contract**: Add an ownerless `OAuthState` entity/table containing UUID ID, unique hash-only state lookup value, indexed expiry, nullable consumption timestamp, and server-created timestamp. It has no `User` relationship, purpose field, raw state, token, entitlement, or lifecycle-event fields. Create a forward Alembic revision depending on `20260806_01`: create/index `oauth_states`, then replace `ck_auth_grants_purpose_allowed` so owned `AuthGrant` permits only `onboarding` and `token_issuance`; retain its required `user_id`, hash uniqueness, and existing indexes. Downgrade restores the three-purpose constraint before dropping `oauth_states`; outstanding OAuth starts are intentionally invalidated by rollback. Extend child-before-parent fixture cleanup and add OAuth-state factories for valid, expired, and consumed records without a user.

#### 2. Author static Demo EULA content and version source

**File**: `docs/eula-demo-v1.md` (new)

**Intent**: Provide the exact repository-owned terms the developer reads before acceptance, using a fixed version identifier that the API and database record.

**Contract**: Define concise Demo terms covering informational/source-backed Azure-limitation data, no completeness or fitness guarantee, Demo-only scope, acceptable use, no automatic remediation, and version/change notice. The terms are product copy for this MVP, not a claim of legal review. Expose a single stable version constant from application code rather than deriving the version from mutable prose at runtime. Load the EULA content once at application startup and fail fast if the file is missing, rather than reading from disk per request; resolve the path relative to the application module, not the process working directory.

#### 3. Add typed onboarding schemas and HTTP mocking dependency

**Files**: `schemas.py`, `pyproject.toml`, `uv.lock`

**Intent**: Make FastAPI-generated OpenAPI documentation the supported developer interface for the JSON-only onboarding flow and enable deterministic HTTPX mocks for the GitHub boundary.

**Contract**: Define models for OAuth callback/onboarding-next-step, EULA document metadata/content, EULA acceptance request and response, license summary, lifecycle-safe token creation request/response, and expiration response. The callback exposes `next_action`, user login, onboarding credential, and its expiry; EULA acceptance returns license summary plus issuance credential. EULA acceptance requires the advertised version; future token-name payloads are bounded and non-empty. Responses may expose user login, opaque token IDs, timestamps, license type/status, and short-lived credentials, but never token hashes, GitHub access tokens, OAuth-state hashes, or stored raw API tokens. Add only the pre-approved dev dependency `respx` and regenerate `uv.lock` using `uv` so Phase 2 mocks GitHub HTTP calls without contacting GitHub.

#### 4. Replace OAuth state generation and callback behavior

**File**: `main.py`

**Intent**: Move OAuth state from a timeless self-signed string to an opaque, separately persisted, expiring, single-use credential and make callback completion create EULA-pending onboarding state rather than silently granting consent or a license.

**Contract**: `GET /auth/login` generates a random opaque value, persists only a domain-appropriate hash in `OAuthState` with short TTL, and redirects to GitHub with that raw state. `GET /auth/callback` validates state without consuming it before provider I/O, exchanges the code with explicit outbound timeouts, and maps GitHub transport/non-success/malformed-identity failures to `502` without local mutation. In one PostgreSQL transaction, conditionally claim the still-unconsumed, unexpired state with `UPDATE … WHERE … RETURNING`, upsert the GitHub user by unique `github_id`, create an owned `AuthGrant(purpose="onboarding")`, and commit them together. A failed conditional claim produces one generic `400` for malformed, expired, or replayed state. Callback completion does not set EULA fields or create a license. It returns a typed JSON response — replacing `token_grant` — with `next_action` (for example `"accept_eula"`), the raw one-time onboarding credential, its expiry timestamp, and user login. Onboarding and issuance credentials are returned only in typed JSON bodies and are supplied to later endpoints in `Authorization: Bearer <credential>` headers; never place them in redirects, query strings, or response headers.

#### 5. Add EULA read and acceptance endpoints

**File**: `main.py`

**Intent**: Let the holder of onboarding state retrieve the static EULA and explicitly accept the exact current version before entitlement or token issuance is possible.

**Contract**: Add `GET /auth/eula`, authenticated with a valid owned onboarding credential in the `Authorization` header, returning versioned EULA metadata/content without consuming its grant. Add `POST /auth/eula/accept`, using the same header and an acceptance body with the advertised EULA version. A version mismatch returns `409` and leaves the grant usable. Valid acceptance conditionally claims the owned onboarding grant and, in one transaction, updates the user's EULA version/timestamp only if needed, ensures exactly one active `demo` license exists, appends `eula_accepted` and `demo_license_assigned` events only for real transitions, and creates an owned one-time `token_issuance` `AuthGrant`. The active-license index remains the DB backstop; serialize per-user state evaluation so two valid onboarding grants cannot duplicate lifecycle transitions. Repeated acceptance with a new valid onboarding flow is idempotent for consent/license state and must not create duplicate active Demo licenses or duplicate transition events.

#### 6. Protect OAuth and onboarding secrets in logs

**Files**: `main.py`, `tests/test_logging_middleware.py`, `tests/test_auth_oauth.py`, `tests/test_onboarding.py`

**Intent**: Close the immediate logging exposure created by OAuth's required callback query string before the new state machine is released.

**Contract**: Suppress or sanitize Uvicorn access-log request lines so OAuth callback state is not emitted, while retaining existing method/path/status request logs. Assert OAuth state, GitHub access token, onboarding credential, and provider-response details remain absent from normal logs, exception logs, and error bodies. This does not replace the Phase 4 full-journey secret-regression suite.

### Success Criteria:

#### Automated Verification:

- The forward migration creates `oauth_states`, restricts `AuthGrant` to owned onboarding/issuance purposes, and upgrades/downgrades around `20260806_01`: `uv run alembic upgrade head; uv run alembic downgrade 20260806_01; uv run alembic upgrade head`
- OAuth login stores only a state hash in `oauth_states`; malformed, expired, replayed, and concurrent callback attempts yield one winner with no partial entitlement state: `uv run pytest tests/test_auth_oauth.py -v`
- Mocked GitHub token/user HTTP responses create one EULA-pending local user and one owned onboarding grant, while concurrent distinct states for one GitHub identity preserve a single local user: `uv run pytest tests/test_auth_oauth.py -v`
- OAuth callback alone cannot create a token, Demo license, EULA state, or lifecycle event; provider failures leave the state reusable until expiry: `uv run pytest tests/test_auth_oauth.py tests/test_onboarding.py -v`
- EULA retrieval with a Bearer onboarding credential returns repository-owned terms without consuming its grant; acceptance rejects a version mismatch with `409` and preserves the grant: `uv run pytest tests/test_onboarding.py -v`
- Valid and concurrent acceptance records exactly one Demo license and transition-event set, creates one issuance grant per consumed onboarding grant as appropriate, and rejects replay: `uv run pytest tests/test_onboarding.py -v`
- OAuth state, GitHub access token, and onboarding credential stay absent from middleware/Uvicorn logs and error bodies: `uv run pytest tests/test_logging_middleware.py tests/test_auth_oauth.py tests/test_onboarding.py -v`
- Static checks pass: `uv run ruff check main.py models.py schemas.py migrations tests/test_auth_oauth.py tests/test_onboarding.py; uv run mypy main.py models.py schemas.py`

#### Manual Verification:

- With a configured GitHub OAuth app, begin at `/auth/login`, approve GitHub access, inspect the typed callback response, use its Bearer onboarding credential to retrieve the EULA in OpenAPI or an HTTP client, then submit its current version and confirm the next action is token issuance.
- Repeat callback, acceptance, and stale-version requests; confirm consumed credentials cannot advance state, version mismatch allows a retry, and no duplicate license/event is created.

**Implementation Note**: After completing this phase and all automated verification passes, pause for human confirmation that the live GitHub flow and explicit consent sequence were successful before proceeding.

---

## Phase 3: One-Time Token Issuance, Owner Expiration, and Demo Enforcement

### Overview

Finish the self-service lifecycle by moving token issuance off query credentials, returning an opaque token ID only at creation, replacing impossible HMAC expiration with owner authorization, and enforcing the Demo-only access policy consistently.

### Changes Required:

#### 1. Implement scoped one-time token issuance

**File**: `main.py`

**Intent**: Replace `GET /auth/token?grant=...` with a typed state-changing endpoint that consumes only a valid issuance credential generated after explicit EULA acceptance.

**Contract**: Accept the issuance credential in `Authorization: Bearer <credential>` with a validated token-name payload. Verify that it is an owned `AuthGrant` with purpose exactly `token_issuance`, valid expiry, and no consumption; atomically consume it as token creation succeeds. An `onboarding` grant is the wrong-purpose negative case; OAuth state cannot be presented here because it is persisted solely in `OAuthState`. Create a 90-day `Token` using `hash_token`, return the raw value only in the creation response alongside token ID/name/expiry, and append one `token_created` lifecycle event without storing raw token material. Expired, malformed, wrong-purpose, or replayed credentials cannot create a token.

#### 2. Replace expiration with token-ID owner authorization

**Files**: `main.py`, `schemas.py`

**Intent**: Remove the server-secret HMAC `user_id` query contract and let an authenticated, licensed developer expire an owned token without submitting a raw token or hash.

**Contract**: Replace the existing expiration route with a typed `POST /auth/tokens/{token_id}/expire` protected by `require_active_license`. It finds only the target token belonging to the dependency's user, sets its expiry to the current UTC time, and returns the typed expired result. An unknown or another user's token ID produces a non-disclosing not-found response; repeated expiration is idempotent. Remove `_sign_user_id`, `_verify_hmac_user_id`, `_create_token_grant`, `TOKEN_GRANT_TTL`, the `SECRET_KEY` startup requirement, and every public contract/test dependent on the old signed user-ID or issuance handoffs. The Phase 2 `OAuthState` table and its callback-consumption logic remain; only the legacy signed issuance grant is removed.

#### 3. Enforce active Demo licensing at all protected boundaries

**File**: `auth.py`

**Intent**: Turn the current implicit single-license assumption into an explicit MVP access invariant.

**Contract**: Update `require_active_license` to require `License.license_type == "demo"` and `is_active` for the current user on every protected request, with the lookup made safe against multiple rows (e.g., `scalars().first()`) — the Phase 1 partial unique index makes "at most one active license per user" a DB invariant, so this is defense-in-depth, not the enforcement point. Reuse it for token expiration and retain the existing 401-before-403 ordering from `get_current_user`. Token issuance independently verifies the current active Demo entitlement before persisting a token, so entitlement changes between consent and issuance cannot bypass the gate.

#### 4. Update token and protected-route tests

**Files**: `tests/test_auth_token.py`, `tests/test_auth_dependencies.py`, `tests/test_auth_probe.py`, `tests/test_limitations_search.py`

**Intent**: Replace scaffold-only HMAC tests with public-contract regression coverage and prove S-01 remains protected by the strengthened Demo-only gate.

**Contract**: Cover one-time issuance, 90-day expiry, hash-only persistence, raw-token one-response visibility, grant failures, owner-only expiration by opaque ID, expiration-to-401, active non-Demo rejection, active Demo success, and mid-token-life Demo deactivation. Update search/probe setup only as needed to preserve their existing access assertions; no change to query/provenance semantics.

### Success Criteria:

#### Automated Verification:

- A consumed EULA acceptance produces one issuance credential that creates exactly one named hash-only token and returns raw token + opaque ID only in its creation response: `uv run pytest tests/test_auth_token.py tests/test_onboarding.py -v`
- Malformed, expired, wrong-purpose onboarding, and replayed issuance credentials cannot create tokens: `uv run pytest tests/test_auth_token.py -v`
- A valid owned Demo token expires an owned target token by ID; another user cannot; the target is rejected with 401 afterwards: `uv run pytest tests/test_auth_token.py -v`
- Active non-Demo licenses are rejected with 403, while valid active Demo licenses continue to authorize `/auth/probe` and `/limitations/search`: `uv run pytest tests/test_auth_dependencies.py tests/test_auth_probe.py tests/test_limitations_search.py -v`
- No remaining application route, schema, test, environment requirement, or deployment instruction imports the removed HMAC helpers or requires `SECRET_KEY`: `uv run pytest tests/test_auth_token.py -v; uv run ruff check main.py auth.py schemas.py tests`
- Type checking passes: `uv run mypy main.py auth.py schemas.py tests/test_auth_token.py tests/test_auth_dependencies.py`

#### Manual Verification:

- Create two differently named tokens through the documented flow, call the protected search endpoint with each, then expire one by its returned ID using the other; confirm only the target is rejected.
- Attempt the expiration endpoint with a token from a different test user and confirm it reveals neither target ownership nor token details.

**Implementation Note**: After completing this phase and all automated verification passes, pause for human confirmation that multi-token ownership and expiration behavior worked against a disposable environment before proceeding.

---

## Phase 4: Documentation, Security Regression Coverage, and Release Verification

### Overview

Make the JSON onboarding flow self-service for developers, correct the deployment contract, and prove the complete lifecycle remains secret-safe under both successful and failing requests.

### Changes Required:

#### 1. Document developer onboarding and token operations

**File**: `README.md`

**Intent**: Provide an end-to-end, API-first operating guide that a developer can follow without relying on implementation internals or server secrets.

**Contract**: Document required local environment variables, GitHub callback configuration, the OAuth → EULA → Demo license → token creation sequence, how to preserve a raw token after its sole display, Bearer use against `/limitations/search`, token-ID expiration using another valid owned token, and clear warnings not to put raw tokens/grants in source control, logs, shell history, or production `TEST_DATABASE_URL`. Refer readers to OpenAPI for typed payload details rather than duplicating response schemas.

#### 2. Correct Railway deployment variable documentation

**File**: `context/deployment/deploy-plan.md`

**Intent**: Align the Railway service-variable table and setup steps with runtime startup requirements and the real OAuth callback contract.

**Contract**: Add `APP_URL` as the canonical public application origin; retain the prohibition on committing/printing values for all remaining sensitive configuration, including OAuth client credentials and `TOKEN_HASH_SALT`. Remove `SECRET_KEY` from the service-variable table, setup instructions, and rotation guidance because no post-Phase-3 flow uses signing. Update examples and verification checklist without actual secret values. Document the distinct durable boundaries: callback state is stored in `OAuthState`; onboarding and issuance credentials are stored in owned `AuthGrant` rows.

#### 3. Extend secret-safe logging and complete journey tests

**Files**: `main.py`, `tests/test_logging_middleware.py`, `tests/test_onboarding.py` (new), `tests/test_auth_oauth.py`, `tests/test_auth_token.py`

**Intent**: Ensure all new bearer values and raw API tokens remain absent from logs/error responses — including uvicorn's access log, which records the full request line (query string included) and is the live leak channel for today's `?grant=`/`?sig=` endpoints — while mocked OAuth plus API endpoints prove the full supported journey.

**Contract**: Retain and regression-test the Phase 2 Uvicorn access-log protection alongside the existing `uvicorn.error` handling in `main.py`. Reuse the repository's direct non-propagating logger capture. Exercise successful onboarding/token issuance and failure paths containing raw token, OAuth state, onboarding credential, and issuance credential; assert none appear in captured logs or response error bodies. Retain a test asserting that a request carrying callback query state produces no access-log record containing that value. Add an integration journey that mocks only GitHub HTTP exchanges and performs `OAuthState` callback → EULA fetch → acceptance → token creation → authenticated search → owned expiration → rejected target token. Do not contact GitHub or add browser E2E.

#### 4. Update project verification instructions and lock state only if dependencies change

**Files**: `README.md`

**Intent**: Keep documented commands aligned with the existing `uv`, pytest, Ruff, and mypy workflow while avoiding unnecessary dependency churn.

**Contract**: The Phase 2 `respx` dev dependency and lock update are already complete before this phase; no further dependency change is expected. Keep final documented verification commands PowerShell-safe with explicit paths or repository-wide commands, never shell globs that Windows PowerShell fails to expand.

### Success Criteria:

#### Automated Verification:

- Complete mocked onboarding journey succeeds and replay/failure cases remain rejected: `uv run pytest tests/test_auth_oauth.py tests/test_onboarding.py tests/test_auth_token.py -v`
- Token, OAuth-state, onboarding-credential, and issuance-credential values are absent from success logs, auth failures, 500 response/log paths, and uvicorn access-log output: `uv run pytest tests/test_logging_middleware.py -v`
- Existing auth and protected-search regressions pass: `uv run pytest tests/test_auth_dependencies.py tests/test_auth_probe.py tests/test_limitations_search.py -v`
- Full suite, lint, and type checks pass: `uv run pytest tests/ -v; uv run ruff check .; uv run mypy .`

#### Manual Verification:

- Follow the README in a clean local environment with a real GitHub OAuth app, using OpenAPI or an HTTP client only; complete the flow without inspecting application source or generating a server HMAC.
- On Railway or equivalent staging, verify the callback origin equals `APP_URL`, required variables are configured without logging their values, `/health` remains healthy, the deployed package includes `docs/eula-demo-v1.md` (service starts and the EULA endpoint serves content), and a freshly issued token can call the deployed protected search endpoint.
- Review an issuance response once, confirm the token can be used, and confirm the README clearly warns that it cannot be recovered later.

**Implementation Note**: After completing this phase and all automated verification passes, pause for human confirmation that the clean-environment onboarding and deployed callback verification were successful before release.

---

## Testing Strategy

### Unit Tests:

- Opaque OAuth-state and owned-grant creation, hashing, purpose validation, TTL evaluation, and atomic single-use consumption.
- EULA version validation; idempotent license assignment; non-duplicating lifecycle event creation.
- `get_current_user` 401 behavior and `require_active_license` 403 behavior for active Demo, inactive Demo, and active non-Demo licenses.
- Token owner lookup/expiration and hash-only storage.

### Integration Tests:

- Mock GitHub token/user HTTP calls, not GitHub itself.
- OAuth login/callback through `OAuthState` → EULA fetch with an onboarding Bearer credential → explicit acceptance → owned issuance grant → one-time token issuance → protected search → owned expiration → target rejection.
- Invalid, expired, mismatched-purpose, replayed, and concurrent OAuth-state/owned-grant paths; concurrent states for one GitHub identity preserve one local user.
- Existing search endpoint remains protected and preserves its provenance contract.
- Normal and error logging never exposes bearer credentials or raw API tokens, including the uvicorn access log (full request line with query string).

### Manual Testing Steps:

1. Configure a disposable PostgreSQL database and all documented local OAuth/auth variables; run migrations and start the service.
2. Register the local callback URL with a real GitHub OAuth app, start `GET /auth/login`, and confirm the callback response requires EULA acceptance rather than silently granting access.
3. Retrieve and inspect the versioned Demo terms via the documented JSON endpoint; accept exactly that version and confirm one Demo license/event set exists.
4. Create two named tokens, store each outside the terminal history, and use each against `GET /limitations/search` with a bearer header.
5. Use one token to expire the other by opaque ID; verify the target gets 401 while the actor remains usable.
6. Repeat a callback state, onboarding credential, and issuance credential; verify each is rejected after consumption. Submit an outdated EULA version first and confirm the service returns `409` without consuming the onboarding credential.
7. Review application logs and error bodies for the exercised flow; confirm no token, OAuth state, onboarding credential, or issuance credential appears.

## Performance Considerations

This MVP has low QPS and a small dataset. The added paths perform indexed lookups by hashed credential/token and user ID only. Transient credential records should be indexed by credential hash and expiry; expired entries may be retained initially for audit/debug evidence or cleaned with a future scheduled maintenance task, but cleanup is not a request-path prerequisite. OAuth calls occur only during callback, never while serving protected limitations.

## Migration Notes

- The completed lifecycle migration remains `20260806_01_create_onboarding_lifecycle_state.py`; the OAuth-state split is a new forward revision depending on it and must be tested from both that existing schema and a fresh `base` database.
- Existing users created by F-03 have an acceptance timestamp but no EULA version. Treat them as EULA-pending for S-02: they must complete explicit acceptance of the current Demo terms before any new token issuance, while existing valid tokens continue to be governed by the explicit active-Demo check.
- The OAuth-state split downgrade intentionally drops outstanding pre-identity `OAuthState` rows and restores the original `AuthGrant` purpose constraint. It is only for controlled local verification; production rollback remains forward-only.
- The old `GET /auth/token` and HMAC-based expiration contract must be removed/replaced rather than retained as a compatibility bypass; this service has no published stable client surface yet.
- Rollback of code cannot safely undo user consents, issued tokens, or lifecycle events. Database schema downgrade is only for controlled local verification; production remediation should be forward-only.

## References

- PRD: `context/foundation/prd.md` — US-02; FR-001–FR-006; Access Control; guardrails.
- Roadmap: `context/foundation/roadmap.md` — S-02 and its explicit onboarding/token outcome.
- Test strategy: `context/foundation/test-plan.md` — Risk #3/#4 and §6.4 auth/licensing regression guidance.
- Completed auth scaffold: `context/archive/2026-07-29-auth-scaffold-token-license/plan.md` and `reviews/impl-review.md`.
- Ownership-correction research: `context/changes/developer-onboarding-token/research.md`.
- Current implementation: `main.py:119-373`, `auth.py:31-80`, `models.py:66-152`, `logging_middleware.py:43-91`.
- Operations: `README.md`, `context/deployment/deploy-plan.md:67-76`.

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Persist Consent, Lifecycle, and One-Time Credentials

#### Automated

- [x] 1.1 Fresh-database migration recreation and seed verification pass: `uv run pytest tests/test_seed_import.py -v` — f551635
- [x] 1.2 New migration upgrades, downgrades to `20260729_02`, and re-upgrades cleanly — f551635
- [x] 1.3 Auth fixture cleanup removes all new lifecycle state: `uv run pytest tests/test_auth_dependencies.py -v` — f551635
- [x] 1.4 Persistence lint and type checks pass: `uv run ruff check models.py migrations tests/conftest.py; uv run mypy models.py tests/conftest.py` — f551635

#### Manual

- [x] 1.5 Schema inspection confirms no raw token or raw grant persistence — f551635
- [x] 1.6 Controlled downgrade/re-upgrade preserves pre-existing schema objects — f551635

### Phase 2: Explicit OAuth and EULA Onboarding State Machine

#### Automated

- [x] 2.1 OAuth-state split migration upgrades, downgrades to `20260806_01`, and re-upgrades cleanly — d2cb2b5
- [x] 2.2 OAuth state is hash-only, opaque, expiring, single-use, and rejects malformed/expired/replayed values — d2cb2b5
- [x] 2.3 Mocked GitHub callback atomically creates one EULA-pending identity and owned onboarding grant, including concurrent identity/state cases — d2cb2b5
- [x] 2.4 Callback/provider failures cannot create a token, Demo license, EULA state, lifecycle event, or partial state consumption — d2cb2b5
- [x] 2.5 EULA delivery with Bearer onboarding credential and version-mismatch retry behavior pass — d2cb2b5
- [x] 2.6 Explicit acceptance atomically assigns one Demo license, records transition lifecycle events, creates issuance state, and rejects replay/concurrent duplication — d2cb2b5
- [x] 2.7 OAuth state, GitHub access token, and onboarding credential are absent from logs and error bodies — d2cb2b5
- [x] 2.8 Onboarding migration, lint, and type checks pass: `uv run ruff check main.py models.py schemas.py migrations tests/test_auth_oauth.py tests/test_onboarding.py; uv run mypy main.py models.py schemas.py` — d2cb2b5

#### Manual

- [x] 2.9 Real GitHub login completes the explicit EULA acceptance sequence using Bearer onboarding state — d2cb2b5
- [x] 2.10 Replayed callback/acceptance credentials cannot advance state or duplicate entitlement events; stale EULA version preserves retry ability — d2cb2b5

### Phase 3: One-Time Token Issuance, Owner Expiration, and Demo Enforcement

#### Automated

- [x] 3.1 One issuance credential creates one named hash-only token and returns raw token + opaque ID only once: `uv run pytest tests/test_auth_token.py tests/test_onboarding.py -v` — 39dd520
- [x] 3.2 Invalid, expired, wrong-purpose onboarding, and replayed issuance credentials are rejected: `uv run pytest tests/test_auth_token.py -v` — 39dd520
- [x] 3.3 Owner token expiration by target ID works, hides other-user tokens, and makes target token return 401: `uv run pytest tests/test_auth_token.py -v` — 39dd520
- [x] 3.4 Active non-Demo license rejection and active Demo access to probe/search pass: `uv run pytest tests/test_auth_dependencies.py tests/test_auth_probe.py tests/test_limitations_search.py -v` — 39dd520
- [x] 3.5 Removed HMAC contract and `SECRET_KEY` requirement have no remaining application/test/deployment dependency: `uv run pytest tests/test_auth_token.py -v; uv run ruff check main.py auth.py schemas.py tests` — 39dd520
- [x] 3.6 Token lifecycle type checks pass: `uv run mypy main.py auth.py schemas.py tests/test_auth_token.py tests/test_auth_dependencies.py` — 39dd520

#### Manual

- [x] 3.7 Two named tokens can be used independently and one can expire the other by ID — 39dd520
- [x] 3.8 A different user cannot discover or expire another user's token — 39dd520

### Phase 4: Documentation, Security Regression Coverage, and Release Verification

#### Automated

- [x] 4.1 Complete mocked onboarding journey and replay/failure checks pass: `uv run pytest tests/test_auth_oauth.py tests/test_onboarding.py tests/test_auth_token.py -v` — 1ae6856
- [x] 4.2 OAuth state, onboarding/issuance credentials, and raw tokens are absent from logs and error bodies: `uv run pytest tests/test_logging_middleware.py -v` — 1ae6856
- [x] 4.3 Existing auth/probe/protected-search regressions pass: `uv run pytest tests/test_auth_dependencies.py tests/test_auth_probe.py tests/test_limitations_search.py -v` — 1ae6856
- [x] 4.4 Full suite, lint, and type checks pass: `uv run pytest tests/ -v; uv run ruff check .; uv run mypy .` — 1ae6856

#### Manual

- [x] 4.5 README-driven clean-environment onboarding completes without server internals — 1ae6856 (manual verification attestation)
- [x] 4.6 Deployed callback origin, Railway variables, health, and fresh protected search are verified — 1ae6856 (manual verification attestation)
- [x] 4.7 One-time raw-token display and recovery warning are confirmed in the live flow — 1ae6856 (manual verification attestation)
