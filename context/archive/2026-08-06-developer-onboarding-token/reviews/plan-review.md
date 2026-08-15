<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Developer Onboarding Token

- **Plan**: context/changes/developer-onboarding-token/plan.md
- **Mode**: Deep
- **Date**: 2026-08-06
- **Verdict**: REVISE → SOUND (after fixes)
- **Findings**: 2 critical · 4 warnings · 1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | WARNING |
| Blind Spots | FAIL |
| Plan Completeness | WARNING |

## Grounding

13/13 paths ✓ (docs/ is new, expected), 8/8 symbols ✓, brief↔plan ✓, Progress↔phases ✓

## Findings

### F1 — Uvicorn access log leaks credentials; plan's logging tests miss it

- **Severity**: ❌ CRITICAL
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 4 §3 (secret-safe logging), Testing Strategy
- **Detail**: The middleware the plan cites is already clean (Starlette `scope["path"]` excludes query strings). The actual leak is uvicorn's access log, which records the full request line including `?grant=`/`?sig=`, is unsuppressed in the repo (only `uvicorn.error` is filtered, main.py:96), and lands in Railway logs today. Phase 4's logger-capture tests would pass while this channel stays open, leaving test-plan.md Risk #4 unclosed.
- **Fix A ⭐ Recommended**: Suppress/clean uvicorn access logs + extend Phase 4 tests to assert on access-log output
  - Strength: Closes the verified live leak; makes the "absent from logs" criteria honest.
  - Tradeoff: One more config area (uvicorn log config) to test.
  - Confidence: HIGH — sub-agent verified no access-log config exists.
  - Blind spot: Railway platform-level request logs (outside app control) not investigated.
- **Fix B**: Documentation-only mitigation
  - Strength: Zero code; post-change credentials no longer travel in query strings anyway.
  - Tradeoff: A future endpoint that reintroduces query credentials leaks silently; tests give no guardrail.
  - Confidence: MEDIUM — acceptable only if access logs stay default.
- **Decision**: FIXED via Fix A — Phase 4 §3 now covers uvicorn access-log suppression and a query-credential access-log test; success criteria and Testing Strategy updated.

### F2 — Callback response contract undefined after token_grant removal

- **Severity**: ❌ CRITICAL
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 §3, Phase 3 §2
- **Detail**: Phase 3 removes `_create_token_grant`, but the callback response (main.py:268-275) currently carries `token_grant`. Phase 2 §3 didn't state the replacement response shape — the Phase 3 implementer would have to guess.
- **Fix**: Define the callback's typed response schema explicitly in Phase 2 §2/§3 and note in Phase 3 that it replaces the `token_grant` field.
- **Decision**: FIXED — Phase 2 §3 now specifies the typed JSON response (`next_action`, onboarding credential, expiry, login); Phase 3 §2 removal list extended with `_create_token_grant`/`TOKEN_GRANT_TTL` and cross-references the Phase 2 replacement.

### F3 — Multi-active-license crash latent in scalar() lookups

- **Severity**: ⚠️ WARNING
- **Impact**: 🔬 HIGH — architectural stakes; think carefully before deciding
- **Dimension**: Architectural Fitness
- **Location**: Phase 3 §3 (auth.py), Phase 2 §4 (license assignment)
- **Detail**: All license lookups (auth.py:69-80, main.py:254-260, main.py:305-310) use `db.scalar()` with non-unique filters, but `ix_licenses_user_id` is non-unique — a second active license raises `MultipleResultsFound` → 500. Phase 2 §4 promised "exactly one active demo license" without an enforcement mechanism.
- **Fix A ⭐ Recommended**: Partial unique index on `licenses(user_id) WHERE is_active` — DB-enforced invariant
  - Strength: Crash impossible; the promise becomes a constraint, not a convention.
  - Tradeoff: Touches the existing licenses table in Phase 1's migration.
  - Confidence: HIGH — Postgres supports partial indexes; matches "exactly one" wording exactly.
  - Blind spot: Existing deployed rows must be checked for violations before the index applies (likely none — scaffold era).
- **Fix B**: Code-level hardening (`scalars().first()` + ordered lookup)
  - Strength: No schema change to existing tables; simpler migration.
  - Tradeoff: Silently picks one license when duplicates exist; races can still create two active rows.
  - Confidence: MEDIUM — fixes the 500, not the invariant.
- **Decision**: FIXED via Fix A — Phase 1 migration contract now includes the partial unique index (with pre-apply data check); Phase 3 §3 notes `scalars().first()` as defense-in-depth.

### F4 — EULA file read pattern and deployment packaging unspecified

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 §1
- **Detail**: `docs/eula-demo-v1.md` is a new runtime file dependency with no existing file-serving pattern in the codebase. The plan didn't say per-request read vs startup load, and didn't verify Railpack packaging includes `docs/` — a missing file becomes a production-only 500.
- **Fix**: State "load once at startup (fail fast if missing)" in Phase 2 §1, and add a `docs/` packaging check to Phase 4's Railway verification step.
- **Decision**: FIXED — Phase 2 §1 now specifies startup load with fail-fast and module-relative path resolution; Phase 4 manual verification includes the docs/ packaging check.

### F5 — HTTP mocking dependency needed but Phase 4 forbids dependency changes

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 success criteria vs Phase 4 §4
- **Detail**: Phase 2 requires "mocked GitHub token/user HTTP responses" but the suite has no HTTP mocking tool (httpx + pytest only, no respx/httpx-mock). Phase 4 §4 said "no package is required... do not modify dependencies" — a direct contradiction.
- **Fix**: Amend Phase 4 §4 to pre-approve a dev-only mocking dependency (e.g., respx), or specify the monkeypatch pattern explicitly in Phase 2.
- **Decision**: FIXED — Phase 4 §4 now pre-approves a dev-only HTTP mocking library (e.g., respx) via the normal `uv` workflow; Phase 2 success criteria reference it.

### F6 — Grant must stay in response body, not redirect URL

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Architectural Fitness
- **Location**: Phase 2 §3/§4 ("selected non-query API contract")
- **Detail**: The plan mandated non-query credential transport but didn't explicitly forbid putting the onboarding credential in a redirect URL — the common OAuth-callback pattern that would reintroduce the F1 access-log leak.
- **Fix**: Add one line to Phase 2 §3: credentials are returned only in typed JSON response bodies, never in redirect URLs or headers.
- **Decision**: FIXED — Phase 2 §3 now pins credentials to JSON response bodies only.

### F7 — SECRET_KEY rotation semantics undocumented

- **Severity**: 👁 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 4 §2 (deploy-plan.md correction)
- **Detail**: Phase 4 adds `SECRET_KEY` to the deploy doc, but rotation guidance covers only `TOKEN_HASH_SALT` and the OAuth secret. After this change `SECRET_KEY` signs nothing durable (grants become DB rows), so rotation becomes nearly free.
- **Fix**: Note in Phase 4 §2 that rotating `SECRET_KEY` post-change does not invalidate issued tokens or pending grants.
- **Decision**: FIXED — Phase 4 §2 contract now includes the rotation-semantics note.
