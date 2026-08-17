<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: MCP Tool Wrapper Implementation Plan

- **Plan**: `context/changes/mcp-tool-wrapper/plan.md`
- **Scope**: Phases 1–3 of 3
- **Date**: 2026-08-16
- **Verdict**: REJECTED
- **Findings**: 1 critical, 3 warnings, 0 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | PASS |
| Safety & Quality | FAIL |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Findings

### F1 — Bearer token may be sent over insecure HTTP

- **Severity**: ❌ CRITICAL
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: `mcp_server.py:55`
- **Detail**: `_validate_base_url` accepts both `http` and `https` for every host, while `AzLimitsApiClient.search_limitations` sends the long-lived configured bearer token in an `Authorization` header. A non-local HTTP endpoint can expose that token and protected query data to network interception, conflicting with the repository's secret-handling and HTTPS guardrails.
- **Fix**: Require `https` for non-loopback hosts; permit `http` only for `localhost`, `127.0.0.1`, and `::1` when local development needs it, and add boundary tests.
- **Decision**: PENDING

### F2 — Response body has no size limit before JSON parsing

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: `mcp_server.py:145`
- **Detail**: The client calls `response.json()` directly after a `200` response. It relies on the current REST endpoint's record limit but does not limit bytes received from a misconfigured or malicious configured upstream, allowing excessive memory/CPU consumption before schema validation.
- **Fix**: Enforce a conservative response-byte limit before JSON decoding and map an over-limit response to `azlimits_upstream_unavailable`.
  - Strength: Preserves the safe failure contract while bounding resource use at the external boundary.
  - Tradeoff: Requires choosing and maintaining a limit compatible with the complete 500-record REST response.
  - Confidence: HIGH — the existing response schema is already validated at this boundary; only the pre-validation byte cap is missing.
  - Blind spot: The maximum serialized size of a valid 500-record production response was not measured during this review.
- **Decision**: PENDING

### F3 — Planned input and transport settings lack direct test coverage

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: `tests/test_mcp_server.py:153`
- **Detail**: Phase 1 required tests for bounded `q`, `region`, and `sku` input validation before a request and integration verification of `httpx.Timeout(10.0)` plus `follow_redirects=False`. The suite only covers an empty `q` and indirectly exercises redirect handling; it does not lock down over-length/non-string filters or client-construction options.
- **Fix**: Add focused tests for invalid/over-length `q`, `region`, and `sku`, plus an assertion that the HTTP client is constructed with the specified timeout and disabled redirects.
- **Decision**: PENDING

### F4 — Tool errors return structured results instead of re-raising

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Plan Adherence
- **Location**: `mcp_server.py:188`
- **Detail**: Phase 2 explicitly required re-raising the dedicated client exceptions and not returning an error string. The adapter instead catches every `AzLimitsMcpError` and returns a handcrafted `CallToolResult`. The inline rationale is that MCP v2 prefixes raised exceptions and would prevent the stable error code from beginning the content; the observed adapter tests pass, but this remains a documented implementation deviation.
- **Fix A ⭐ Recommended**: Amend the plan with the MCP v2 behavior discovery and retain the safe explicit `CallToolResult`.
  - Strength: Preserves the tested stable error-code contract and records why the original mechanism is incompatible with it.
  - Tradeoff: The SDK, rather than an exception, is no longer responsible for setting `is_error=True`.
  - Confidence: HIGH — in-memory adapter tests verify the resulting content begins with the stable error code and `is_error=True`.
  - Blind spot: The review did not validate this behavior against every external MCP host implementation.
- **Fix B**: Re-raise the dedicated exceptions as written in the original plan.
  - Strength: Matches the original adapter-control-flow requirement exactly.
  - Tradeoff: May reintroduce SDK-added message prefixes and break the stable-code-at-content-start contract.
  - Confidence: MEDIUM — the code comment reports this SDK behavior, but the review did not independently reproduce it.
  - Blind spot: Exact MCP v2 exception serialization was not re-tested in this review.
- **Decision**: PENDING

## Verification Evidence

| Command | Result | Evidence |
|---------|--------|----------|
| `uv run pytest tests/test_mcp_server.py -v` | PASS | 19 passed in 7.68s |
| `uv run pytest tests/ -v` | PASS | 84 passed, 3 unrelated Alembic deprecation warnings, in 68.48s |
| `uv run ruff check .` | PASS | All checks passed |
| `uv run mypy .` | PASS | Success: no issues found in 26 source files |

Manual progress items 1.5–1.6, 2.5–2.7, and 3.6–3.8 are marked complete. Commit evidence and the source/docs support the manual secret, schema, documentation, and roadmap checks; live external MCP-host and configured-API interactions were not independently repeated in this review.
