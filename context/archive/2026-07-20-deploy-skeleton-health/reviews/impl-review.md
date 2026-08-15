<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Deploy Skeleton + Health

- **Plan**: context/changes/deploy-skeleton-health/plan.md
- **Scope**: Phase 1 of 1
- **Date**: 2026-07-21
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 1 warning, 0 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | PASS |
| Safety & Quality | PASS |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Findings

### F1 — Railway health-check host baked into code default

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Plan Adherence
- **Location**: main.py:12
- **Detail**: The default `ALLOWED_HOSTS` includes `healthcheck.railway.app`, but the plan explicitly states: "Railway health-check host added at deploy time via Railway service variable — no code change needed." Commit `d0835c9` baked it into the code default, which contradicts the plan's intent. The plan's design keeps source defaults minimal (`localhost,127.0.0.1`) and injects deploy-specific hosts via Railway's environment. This matters because baking deploy-specific hosts into source couples the codebase to a specific deployment environment.
- **Fix A ⭐ Recommended**: Revert default to `localhost,127.0.0.1` and set Railway service variable `ALLOWED_HOSTS=localhost,127.0.0.1,healthcheck.railway.app`
  - Strength: Matches the plan's design intent; keeps source code environment-agnostic; Railway dashboard is the right place for deploy-specific config.
  - Tradeoff: Requires a Railway dashboard change (one-time setup); if the variable is forgotten, health checks fail with 400.
  - Confidence: HIGH — this is exactly what the plan specified, and Railway service variables are the standard mechanism for this.
  - Blind spot: None significant.
- **Fix B**: Accept the drift and update the plan to reflect the new default
  - Strength: No code change needed; the fix solved a real deployment problem (health checks getting 400'd by TrustedHostMiddleware).
  - Tradeoff: Couples source to Railway; future non-Railway deployments inherit Railway-specific defaults; plan becomes a moving target.
  - Confidence: MEDIUM — pragmatic but deviates from the environment-agnostic design principle.
  - Blind spot: Haven't verified whether other deployment targets (if any) would be affected by Railway-specific defaults.
- **Decision**: PENDING
