<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Deploy Skeleton + Health

- **Plan**: `context/changes/deploy-skeleton-health/plan.md`
- **Mode**: Deep
- **Date**: 2026-07-20
- **Verdict**: REVISE
- **Findings**: 0 critical, 1 warning, 0 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | PASS |

## Grounding

Grounding: 4/4 paths ✓, brief↔plan ✓

## Findings

### F1 — TrustedHostMiddleware blocks TestClient requests

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 1 — Test (§3) vs FastAPI Application (§1)
- **Detail**: The plan adds TrustedHostMiddleware with default allowed hosts ["localhost", "127.0.0.1"]. FastAPI's TestClient (Starlette) sends requests with Host: testserver by default. The test described in §3 will receive a 400 response from the middleware before reaching the /health route — the test fails on first run. This is a contradiction between the middleware contract (§1) and the test contract (§3): both are correct in isolation, but they conflict when combined.
- **Fix ⭐ Recommended**: Test sets ALLOWED_HOSTS env var to include "testserver" or uses `TestClient(app, base_url="http://localhost")` to send requests with Host: localhost (which is already in the default allowed hosts).
  - Strength: No production code change; the test adapts to the middleware rather than weakening it.
  - Tradeoff: One extra line in the test setup.
  - Confidence: HIGH — this is a well-known Starlette TestClient behavior.
  - Blind spot: None significant.
- **Decision**: FIXED via recommended fix — test contract updated to use `base_url="http://localhost"`
