# Developer Onboarding Token Implementation Plan

## Overview

Turn the completed auth scaffold into a self-service, API-first onboarding journey. A developer authenticates with GitHub, explicitly reads and accepts versioned Demo terms, receives an active Demo license, creates one named API token that is shown only in its creation response, and can expire any of their tokens by opaque ID.

The implementation replaces scaffold-only handoffs that are not user-completable—automatic consent/license assignment, replayable signed OAuth state and issuance grants, and server-secret HMAC token expiration—with expiring, single-use database-backed lifecycle state. It preserves hash-only token storage, explicit `Depends()` authorization, and secret-safe logging.

## Current State Analysis

The repository has F-03's backend auth foundation and S-01's protected REST search endpoint. `main.py` holds all auth routes inline: GitHub OAuth callback currently auto-sets `User.eula_accepted_at`, creates a Demo license, returns a signed five-minute `token_grant`, and `GET /auth/token` creates a 90-day token. `POST /auth/token/expire` instead requires a `user_id` signature that only the server can derive, so a normal developer cannot use it.

### Key Discoveries:

- `main.py:193-275` verifies a timeless signed OAuth `state`, upserts a user while silently accepting the EULA, creates a Demo license, and returns an issuance grant.
- `main.py:282-373` passes the grant through a query parameter and exposes expiration through an unreachable server-secret HMAC contract.
- `auth.py:36-80` already centralizes valid-token and per-request active-license checks as two chained FastAPI dependencies; this must remain the protected-data boundary.
- `models.py:66-112` and migration `20260729_02` contain user, license, and token state but no consent version, lifecycle-event history, or one-time ephemeral credentials.
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

Keep the API-first architecture and root-level module convention. Add typed request/response schemas for public onboarding contracts and database-backed, short-lived records for OAuth state and scoped onboarding/issuance credentials. Store only opaque random values as hashes, along with owner, purpose, expiry, and consumed timestamp, so the service can validate and atomically consume bearer handoffs without persisting reusable plaintext credentials.

The OAuth callback is only an identity handoff: it verifies and consumes state, exchanges the code with GitHub, upserts the user, and produces onboarding state. EULA acceptance—not login—records consent and creates an active Demo license. Token issuance requires a consumed-on-success issuance credential. Token expiration uses `require_active_license`, looks up an owned token by ID, and moves only that token's expiry to now. Extend the existing `get_current_user` / `require_active_license` chain to make `license_type == "demo"` an explicit MVP invariant.

## Critical Implementation Details

The callback, EULA acceptance, and token issuance transitions must consume their corresponding short-lived credential in the same database transaction as their state mutation. A replay must fail even if it occurs before the credential's TTL ends; never mark a credential consumed before the downstream state change can commit.

## Phase 1: Persist Consent, Lifecycle, and One-Time Credentials

### Overview

Extend the database model so the service can identify accepted Demo terms, retain the required onboarding events, and issue/consume expiring single-use OAuth and onboarding handoffs without storing their raw values.

### Changes Required:

#### 1. Extend user and auth-lifecycle SQLAlchemy models

**File**: `models.py`

**Intent**: Preserve the existing `User`, `License`, and `Token` relationships while adding the minimum durable state needed for versioned consent, required lifecycle evidence, and replay-resistant transient credentials.

**Contract**: Add nullable `User.eula_version` paired with `eula_accepted_at`; add an append-only `LifecycleEvent` entity with UUID ID, user foreign key, constrained event type, non-secret metadata/version context, and server-created timestamp; add an `AuthGrant` entity with UUID ID, user foreign key, hashed opaque credential, purpose (`oauth_state`, `onboarding`, or `token_issuance`), expiry, and nullable consumed timestamp. Give lookup fields appropriate uniqueness/indexes and `back_populates` relationships. Do not add a raw-token or raw-grant column.

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

Replace automatic consent with a secure, self-service OAuth-to-EULA progression. The API exposes versioned, repository-owned Demo terms, issues a one-time onboarding credential after GitHub identity verification, records explicit consent, assigns the Demo license, and emits the two required lifecycle events.

### Changes Required:

#### 1. Author static Demo EULA content and version source

**File**: `docs/eula-demo-v1.md` (new)

**Intent**: Provide the exact repository-owned terms the developer reads before acceptance, using a fixed version identifier that the API and database record.

**Contract**: Define concise Demo terms covering informational/source-backed Azure-limitation data, no completeness or fitness guarantee, Demo-only scope, acceptable use, no automatic remediation, and version/change notice. The terms are product copy for this MVP, not a claim of legal review. Expose a single stable version constant from application code rather than deriving the version from mutable prose at runtime. Load the EULA content once at application startup and fail fast if the file is missing, rather than reading from disk per request; resolve the path relative to the application module, not the process working directory.

#### 2. Add typed onboarding schemas

**File**: `schemas.py`

**Intent**: Make FastAPI-generated OpenAPI documentation the supported developer interface for the JSON-only onboarding flow.

**Contract**: Define models for OAuth callback/onboarding-next-step, EULA document metadata/content, EULA acceptance request and response, license summary, lifecycle-safe token creation request/response, and expiration response. Request payloads require the advertised EULA version and a bounded non-empty token name. Responses may expose user login, opaque token IDs, timestamps, license type/status, and short-lived credentials, but never token hashes, GitHub access tokens, or stored raw API tokens.

#### 3. Replace OAuth state generation and callback behavior

**File**: `main.py`

**Intent**: Move OAuth state from a timeless self-signed string to an opaque, stored, expiring, single-use credential and make callback completion create EULA-pending onboarding state rather than silently granting consent or a license.

**Contract**: `GET /auth/login` creates an opaque OAuth-state value, persists only its hash with purpose and short TTL, and redirects to GitHub with that value. `GET /auth/callback` verifies the unconsumed, unexpired state and consumes it transactionally after GitHub identity verification; it upserts the user login but does not set EULA fields or create a license. It returns a typed JSON response — replacing today's `token_grant` field — with: `next_action` (e.g., `"accept_eula"`), the single-use onboarding credential, its expiry timestamp, and the user's login. Onboarding and issuance credentials are returned only in typed JSON response bodies — never in redirect URLs, query strings, or headers — so they cannot leak into access logs or browser history. Invalid, expired, or replayed state always fails without creating/altering user entitlement state.

#### 4. Add EULA read and acceptance endpoints

**File**: `main.py`

**Intent**: Let the holder of onboarding state retrieve the static EULA and explicitly accept the exact current version before entitlement or token issuance is possible.

**Contract**: Add a JSON endpoint returning versioned EULA metadata/content and an acceptance endpoint that receives the onboarding credential through the selected non-query API contract. Acceptance rejects a stale/mismatched EULA version and consumes the onboarding credential exactly once. In one transaction, it sets the user's EULA acceptance timestamp/version, ensures exactly one active `demo` license exists, appends `eula_accepted` and `demo_license_assigned` lifecycle events when those transitions occur, and returns a one-time token-issuance credential. Repeated acceptance with a new valid onboarding flow is idempotent for consent/license state and must not create duplicate active Demo licenses or duplicate transition events.

### Success Criteria:

#### Automated Verification:

- OAuth login creates a redirect containing an opaque state; valid state is accepted once, while malformed, expired, and replayed state return a controlled client error: `uv run pytest tests/test_auth_oauth.py -v`
- Mocked GitHub token/user HTTP responses (via the pre-approved dev-only HTTP mocking library) produce one EULA-pending local user and preserve identity on repeat login: `uv run pytest tests/test_auth_oauth.py -v`
- OAuth callback alone cannot generate a token or create a Demo license: `uv run pytest tests/test_onboarding.py -v`
- EULA read returns the repository-owned Demo terms and advertised version; acceptance rejects a version mismatch: `uv run pytest tests/test_onboarding.py -v`
- Valid acceptance records version/timestamp, assigns one active Demo license, emits the required non-secret lifecycle events, and rejects credential replay: `uv run pytest tests/test_onboarding.py -v`
- Static checks pass: `uv run ruff check main.py schemas.py tests/test_auth_oauth.py tests/test_onboarding.py; uv run mypy main.py schemas.py`

#### Manual Verification:

- With a configured GitHub OAuth app, begin at `/auth/login`, approve GitHub access, inspect the typed callback response, retrieve the EULA in OpenAPI or an HTTP client, then submit its current version and confirm the next action is token issuance.
- Repeat the same callback/acceptance request and confirm a stale or consumed credential cannot create another license/event or advance the flow.

**Implementation Note**: After completing this phase and all automated verification passes, pause for human confirmation that the live GitHub flow and explicit consent sequence were successful before proceeding.

---

## Phase 3: One-Time Token Issuance, Owner Expiration, and Demo Enforcement

### Overview

Finish the self-service lifecycle by moving token issuance off query credentials, returning an opaque token ID only at creation, replacing impossible HMAC expiration with owner authorization, and enforcing the Demo-only access policy consistently.

### Changes Required:

#### 1. Implement scoped one-time token issuance

**File**: `main.py`

**Intent**: Replace `GET /auth/token?grant=...` with a typed state-changing endpoint that consumes only a valid issuance credential generated after explicit EULA acceptance.

**Contract**: Accept the issuance credential using the same safe non-query credential transport chosen for onboarding and a validated token-name payload. Verify purpose, user ownership, expiry, and unconsumed state; atomically consume it as token creation succeeds. Create a 90-day `Token` using `hash_token`, return the raw value only in the creation response alongside token ID/name/expiry, and append one `token_created` lifecycle event without storing raw token material. Expired, malformed, wrong-purpose, or replayed credentials cannot create a token.

#### 2. Replace expiration with token-ID owner authorization

**Files**: `main.py`, `schemas.py`

**Intent**: Remove the server-secret HMAC `user_id` query contract and let an authenticated, licensed developer expire an owned token without submitting a raw token or hash.

**Contract**: Replace the existing expiration route with a typed `POST /auth/tokens/{token_id}/expire` protected by `require_active_license`. It finds only the target token belonging to the dependency's user, sets its expiry to the current UTC time, and returns the typed expired result. An unknown or another user's token ID produces a non-disclosing not-found response; repeated expiration is idempotent. Remove `_sign_user_id`, `_verify_hmac_user_id`, `_create_token_grant`, `TOKEN_GRANT_TTL`, and every public contract/test dependent on them; the callback's `token_grant` field was already replaced by the typed Phase 2 response.

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
- Malformed, expired, wrong-purpose, and replayed issuance credentials cannot create tokens: `uv run pytest tests/test_auth_token.py -v`
- A valid owned Demo token expires an owned target token by ID; another user cannot; the target is rejected with 401 afterwards: `uv run pytest tests/test_auth_token.py -v`
- Active non-Demo licenses are rejected with 403, while valid active Demo licenses continue to authorize `/auth/probe` and `/limitations/search`: `uv run pytest tests/test_auth_dependencies.py tests/test_auth_probe.py tests/test_limitations_search.py -v`
- No remaining application route, schema, or test imports the removed user-ID HMAC helper: `uv run pytest tests/test_auth_token.py -v; uv run ruff check main.py auth.py schemas.py tests`
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

**Contract**: Add `SECRET_KEY` as a generated service secret used for credential hashing/signing and `APP_URL` as the canonical public application origin; retain the prohibition on committing/printing values. Update the variable-setting example and verification checklist without placing actual secret values in the document. Note in the rotation guidance that after this change `SECRET_KEY` no longer signs durable artifacts (grants/state are database rows), so rotating it does not invalidate issued tokens or pending onboarding flows.

#### 3. Extend secret-safe logging and complete journey tests

**Files**: `main.py`, `tests/test_logging_middleware.py`, `tests/test_onboarding.py` (new), `tests/test_auth_oauth.py`, `tests/test_auth_token.py`

**Intent**: Ensure all new bearer values and raw API tokens remain absent from logs/error responses — including uvicorn's access log, which records the full request line (query string included) and is the live leak channel for today's `?grant=`/`?sig=` endpoints — while mocked OAuth plus API endpoints prove the full supported journey.

**Contract**: Configure uvicorn access logging so request lines with query strings are not emitted at default level (e.g., disable `uvicorn.access` or filter its records), alongside the existing `uvicorn.error` handling in `main.py`. Reuse the repository's direct non-propagating logger capture. Exercise successful onboarding/token issuance and failure paths containing raw token, OAuth state, onboarding credential, and issuance credential; assert none appear in captured logs or response error bodies. Add a test asserting that a request carrying a query-string credential produces no access-log record containing that value. Add an integration journey that mocks only GitHub HTTP exchanges and performs callback → EULA fetch → acceptance → token creation → authenticated search → owned expiration → rejected target token. Do not contact GitHub or add browser E2E.

#### 4. Update project verification instructions and lock state only if dependencies change

**Files**: `README.md`, `pyproject.toml`, `uv.lock` (conditional)

**Intent**: Keep documented commands aligned with the existing `uv`, pytest, Ruff, and mypy workflow while avoiding unnecessary dependency churn.

**Contract**: No runtime package is required for this implementation. One dev-only test dependency is pre-approved: an HTTP mocking library for the GitHub token/user exchanges (e.g., `respx`); add it to the dev dependency group and update `uv.lock` via the normal `uv` workflow. No other dependency changes. The final documented verification commands are PowerShell-safe explicit paths or repository-wide commands, not shell globs that Windows PowerShell fails to expand.

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

- Opaque credential creation, hashing, purpose validation, TTL evaluation, and atomic single-use consumption.
- EULA version validation; idempotent license assignment; non-duplicating lifecycle event creation.
- `get_current_user` 401 behavior and `require_active_license` 403 behavior for active Demo, inactive Demo, and active non-Demo licenses.
- Token owner lookup/expiration and hash-only storage.

### Integration Tests:

- Mock GitHub token/user HTTP calls, not GitHub itself.
- OAuth login/callback → EULA fetch → explicit acceptance → one-time token issuance → protected search → owned expiration → target rejection.
- Invalid, expired, mismatched-purpose, and replayed state/grant paths.
- Existing search endpoint remains protected and preserves its provenance contract.
- Normal and error logging never exposes bearer credentials or raw API tokens, including the uvicorn access log (full request line with query string).

### Manual Testing Steps:

1. Configure a disposable PostgreSQL database and all documented local OAuth/auth variables; run migrations and start the service.
2. Register the local callback URL with a real GitHub OAuth app, start `GET /auth/login`, and confirm the callback response requires EULA acceptance rather than silently granting access.
3. Retrieve and inspect the versioned Demo terms via the documented JSON endpoint; accept exactly that version and confirm one Demo license/event set exists.
4. Create two named tokens, store each outside the terminal history, and use each against `GET /limitations/search` with a bearer header.
5. Use one token to expire the other by opaque ID; verify the target gets 401 while the actor remains usable.
6. Repeat a callback state, onboarding credential, and issuance credential; verify each is rejected after consumption.
7. Review application logs and error bodies for the exercised flow; confirm no token, OAuth state, onboarding credential, or issuance credential appears.

## Performance Considerations

This MVP has low QPS and a small dataset. The added paths perform indexed lookups by hashed credential/token and user ID only. Transient credential records should be indexed by credential hash and expiry; expired entries may be retained initially for audit/debug evidence or cleaned with a future scheduled maintenance task, but cleanup is not a request-path prerequisite. OAuth calls occur only during callback, never while serving protected limitations.

## Migration Notes

- The new migration must follow `20260729_02_create_users_licenses_tokens.py` and be tested from both an existing deployed auth schema and a fresh `base` database.
- Existing users created by F-03 have an acceptance timestamp but no EULA version. Treat them as EULA-pending for S-02: they must complete explicit acceptance of the current Demo terms before any new token issuance, while existing valid tokens continue to be governed by the explicit active-Demo check.
- The old `GET /auth/token` and HMAC-based expiration contract must be removed/replaced rather than retained as a compatibility bypass; this service has no published stable client surface yet.
- Rollback of code cannot safely undo user consents, issued tokens, or lifecycle events. Database schema downgrade is only for controlled local verification; production remediation should be forward-only.

## References

- PRD: `context/foundation/prd.md` — US-02; FR-001–FR-006; Access Control; guardrails.
- Roadmap: `context/foundation/roadmap.md` — S-02 and its explicit onboarding/token outcome.
- Test strategy: `context/foundation/test-plan.md` — Risk #3/#4 and §6.4 auth/licensing regression guidance.
- Completed auth scaffold: `context/archive/2026-07-29-auth-scaffold-token-license/plan.md` and `reviews/impl-review.md`.
- Current implementation: `main.py:119-373`, `auth.py:31-80`, `models.py:66-112`, `logging_middleware.py:43-91`.
- Operations: `README.md`, `context/deployment/deploy-plan.md:67-76`.

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Persist Consent, Lifecycle, and One-Time Credentials

#### Automated

- [x] 1.1 Fresh-database migration recreation and seed verification pass: `uv run pytest tests/test_seed_import.py -v`
- [x] 1.2 New migration upgrades, downgrades to `20260729_02`, and re-upgrades cleanly
- [x] 1.3 Auth fixture cleanup removes all new lifecycle state: `uv run pytest tests/test_auth_dependencies.py -v`
- [x] 1.4 Persistence lint and type checks pass: `uv run ruff check models.py migrations tests/conftest.py; uv run mypy models.py tests/conftest.py`

#### Manual

- [x] 1.5 Schema inspection confirms no raw token or raw grant persistence
- [x] 1.6 Controlled downgrade/re-upgrade preserves pre-existing schema objects

### Phase 2: Explicit OAuth and EULA Onboarding State Machine

#### Automated

- [ ] 2.1 OAuth state is opaque, expiring, single-use, and rejects malformed/expired/replayed values: `uv run pytest tests/test_auth_oauth.py -v`
- [ ] 2.2 Mocked GitHub callback upserts an EULA-pending identity: `uv run pytest tests/test_auth_oauth.py -v`
- [ ] 2.3 Callback alone cannot create a token or Demo license: `uv run pytest tests/test_onboarding.py -v`
- [ ] 2.4 EULA delivery/version mismatch validation passes: `uv run pytest tests/test_onboarding.py -v`
- [ ] 2.5 Explicit acceptance assigns one Demo license, records lifecycle events, and rejects replay: `uv run pytest tests/test_onboarding.py -v`
- [ ] 2.6 Onboarding lint and type checks pass: `uv run ruff check main.py schemas.py tests/test_auth_oauth.py tests/test_onboarding.py; uv run mypy main.py schemas.py`

#### Manual

- [ ] 2.7 Real GitHub login completes the explicit EULA acceptance sequence
- [ ] 2.8 Replayed callback/acceptance credentials cannot advance state or duplicate entitlement events

### Phase 3: One-Time Token Issuance, Owner Expiration, and Demo Enforcement

#### Automated

- [ ] 3.1 One issuance credential creates one named hash-only token and returns raw token + opaque ID only once: `uv run pytest tests/test_auth_token.py tests/test_onboarding.py -v`
- [ ] 3.2 Invalid, expired, wrong-purpose, and replayed issuance credentials are rejected: `uv run pytest tests/test_auth_token.py -v`
- [ ] 3.3 Owner token expiration by target ID works, hides other-user tokens, and makes target token return 401: `uv run pytest tests/test_auth_token.py -v`
- [ ] 3.4 Active non-Demo license rejection and active Demo access to probe/search pass: `uv run pytest tests/test_auth_dependencies.py tests/test_auth_probe.py tests/test_limitations_search.py -v`
- [ ] 3.5 Removed user-ID HMAC contract has no remaining application/test dependency: `uv run pytest tests/test_auth_token.py -v; uv run ruff check main.py auth.py schemas.py tests`
- [ ] 3.6 Token lifecycle type checks pass: `uv run mypy main.py auth.py schemas.py tests/test_auth_token.py tests/test_auth_dependencies.py`

#### Manual

- [ ] 3.7 Two named tokens can be used independently and one can expire the other by ID
- [ ] 3.8 A different user cannot discover or expire another user's token

### Phase 4: Documentation, Security Regression Coverage, and Release Verification

#### Automated

- [ ] 4.1 Complete mocked onboarding journey and replay/failure checks pass: `uv run pytest tests/test_auth_oauth.py tests/test_onboarding.py tests/test_auth_token.py -v`
- [ ] 4.2 OAuth state, onboarding/issuance credentials, and raw tokens are absent from logs and error bodies: `uv run pytest tests/test_logging_middleware.py -v`
- [ ] 4.3 Existing auth/probe/protected-search regressions pass: `uv run pytest tests/test_auth_dependencies.py tests/test_auth_probe.py tests/test_limitations_search.py -v`
- [ ] 4.4 Full suite, lint, and type checks pass: `uv run pytest tests/ -v; uv run ruff check .; uv run mypy .`

#### Manual

- [ ] 4.5 README-driven clean-environment onboarding completes without server internals
- [ ] 4.6 Deployed callback origin, Railway variables, health, and fresh protected search are verified
- [ ] 4.7 One-time raw-token display and recovery warning are confirmed in the live flow
