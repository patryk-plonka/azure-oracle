# Developer Onboarding Token — Plan Brief

> Full plan: `context/changes/developer-onboarding-token/plan.md`
> Research: `context/changes/developer-onboarding-token/research.md`

## What & Why

Make the existing backend auth scaffold usable by a developer without adding a dashboard or CLI. GitHub OAuth will lead to explicit acceptance of versioned Demo terms, active Demo entitlement, one-time token creation, and owner-authorized token expiration; every transition remains source-of-truth backed in the database and preserves the no-raw-secret rule.

## Starting Point

The app already has GitHub OAuth, users/licenses/tokens, hash-only token storage, a five-minute signed issuance grant, and per-request token/license dependencies. Phase 1 added consent/lifecycle tables, but its `AuthGrant` owner requirement cannot represent pre-identity OAuth state, while `main.py` still auto-accepts the EULA, assigns Demo access at callback, and uses signed query handoffs.

## Desired End State

A developer can use the documented JSON/OpenAPI flow to authenticate, read and explicitly accept the current repo-owned Demo EULA, create a named 90-day API token shown only once, and call protected limitation search immediately. A valid owner token can expire any of the developer’s tokens by opaque ID, while all protected routes require a valid token and active `demo` license on every request.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Onboarding surface | JSON/OpenAPI flow | Preserves the API + MCP MVP boundary while making the flow self-service. | Plan |
| EULA evidence | Repo-owned static v1 terms + persisted version | Records exactly what was accepted without adding a full legal/audit system. | Plan |
| OAuth-state ownership | Dedicated hash-only `OAuthState` table | Preserves mandatory ownership for downstream grants while state exists before GitHub identity. | Research |
| OAuth/grant replay | Conditional database claim plus one transaction | Gives exactly one concurrent consumer while rolling back all local mutation on failure. | Plan |
| Credential transport | `Authorization: Bearer` for onboarding/issuance | Avoids query leaks and makes EULA retrieval interoperable. | Plan |
| Provider errors | `400` caller errors / `502` GitHub failures | Separates bad/replayed state from safely retryable provider incidents. | Plan |
| Expiration authorization | Owned token ID via `require_active_license` | Replaces an impossible server-secret HMAC contract without exposing token material. | Plan |
| Licensing | Explicit active `demo` enforcement | Aligns runtime behavior with the Demo-only MVP contract. | Plan |
| Audit scope | Minimal lifecycle events | Meets US-02 evidence needs without building the parked generalized audit feature. | Plan |
| Test approach | Mocked OAuth plus concurrency integration coverage | Proves one-time state claims and identity/entitlement invariants without testing GitHub or adding browser E2E. | Plan |
| Operations | Early callback-log protection; remove dead `SECRET_KEY` | Prevents OAuth query leakage and avoids retaining an unused production secret. | Plan |

## Scope

**In scope:**

- Versioned Demo EULA content and explicit JSON acceptance.
- A dedicated one-time `OAuthState` lifecycle and owned onboarding/issuance grants.
- Consent version persistence, lifecycle events, and schema migration.
- Named hash-only token creation, opaque token ID response, and owner-only expiration.
- Explicit active-Demo authorization checks.
- Mocked OAuth, lifecycle, ownership, replay, and secret-leak regression tests.
- README onboarding guide and deployment documentation for `APP_URL`, OAuth credentials, and `TOKEN_HASH_SALT`.

**Out of scope:**

- Dashboard/HTML UI, CLI, non-GitHub login, token revocation, general audit tooling, and browser E2E.
- MCP tool work, limitation-query changes, region/SKU filtering, and advanced logging.

## Architecture / Approach

The app stores only hashes of random opaque credentials. Ownerless `OAuthState` is created before GitHub identity; after the callback, user-owned `AuthGrant` records carry onboarding and issuance credentials. Conditional PostgreSQL claims ensure one winner under concurrency, and each claim commits only with its user/consent/token transition. Existing FastAPI `Depends()` remains the protected-data boundary: bearer API-token validation produces 401, then active Demo entitlement produces 403.

```mermaid
sequenceDiagram
    participant D as Developer
    participant A as AzLimits API
    participant G as GitHub
    participant DB as Postgres
    D->>A: GET /auth/login
    A->>DB: Store hashed, expiring OAuthState
    A-->>D: Redirect to GitHub
    D->>G: Authorize
    G-->>A: Callback code + state
    A->>DB: Claim OAuthState; upsert user; create onboarding AuthGrant
    A-->>D: One-time onboarding credential
    D->>A: Read EULA; accept current version
    A->>DB: Record consent + Demo license + events; consume credential
    A-->>D: One-time issuance credential
    D->>A: Create named token
    A->>DB: Store token hash + event; consume credential
    A-->>D: Raw token once + opaque token ID
```

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Persistence | Consent version, lifecycle events, one-time credential schema | Migration ordering and ensuring raw credentials are never stored |
| 2. OAuth + EULA | OAuthState split, explicit consent, and Demo entitlement | Atomic claims, provider failure rollback, and concurrent identity/acceptance races |
| 3. Token lifecycle | One-time named issuance, ID-based owned expiration, Demo enforcement | Ownership isolation and preserving protected-search access rules |
| 4. Verification + docs | README/deploy updates and full secret-safe regression coverage | Live callback configuration and credential leakage through error paths |

**Prerequisites:** PostgreSQL test database, GitHub OAuth app for manual verification, and configured `APP_URL`, OAuth credentials, and token hash salt.

**Estimated effort:** ~3–4 sessions across four phases.

## Open Risks & Assumptions

- The short-lived OAuth-state and owned-grant records need a future cleanup policy; expired entries do not block request-path correctness and may remain initially for evidence/debugging.
- Existing F-03 users have timestamps but no accepted EULA version; the migration treats them as EULA-pending for future token creation.
- The Demo terms are intentionally concise MVP product copy and should receive legal review before a production/paid offering.
- A user must keep another valid owned token to expire a different token; losing all credentials is not a self-service recovery flow in this MVP.

## Success Criteria (Summary)

- A real developer completes GitHub login → explicit EULA acceptance → Demo entitlement → one-time token issuance using only the documented API workflow.
- Replayed/expired OAuth state or onboarding/issuance credentials cannot alter entitlement or mint more tokens, including concurrent attempts.
- Tokens are persisted only as hashes, raw values never appear in logs/error bodies, and users can expire only their own token IDs.
- The full pytest suite, Ruff, and mypy pass; deployed callback/health/search flow works with all documented Railway variables.
