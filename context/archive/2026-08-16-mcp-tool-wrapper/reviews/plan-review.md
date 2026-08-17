<!-- PLAN-REVIEW-REPORT -->
# Plan Review: MCP Tool Wrapper Implementation Plan

- **Plan**: context/changes/mcp-tool-wrapper/plan.md
- **Mode**: Deep
- **Date**: 2026-08-16
- **Verdict**: SOUND
- **Findings**: 0 critical 2 warnings 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding
Grounding: 7/7 existing paths ✓, new paths correctly absent, 6/6 symbols ✓, brief↔plan ✓

## Findings

### F1 — Stable error codes have no MCP wire shape

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Plan Completeness
- **Location**: Phase 1 error contract / Phase 2 tool-error mechanism
- **Detail**: Official MCP Python SDK v2 has no typed string error-code field. Ordinary exceptions become `is_error=True` tool results; `MCPError` becomes a JSON-RPC failure the model never sees.
- **Fix A ⭐ Recommended**: Raise a dedicated exception whose message starts with the stable code plus short remediation; do not use `MCPError`.
  - Strength: Matches SDK guidance for execution failures; model and host both see a distinguishable code.
  - Tradeoff: Code lives in text, not a typed field.
  - Confidence: HIGH — documented v2 handling-errors behavior.
  - Blind spot: Some hosts may truncate tool-error text.
- **Fix B**: Raise `MCPError` with the code in `data` for host-only failures.
  - Strength: Structured `data` survives intact on the protocol.
  - Tradeoff: The model sees nothing, so it cannot tell the user to fix the token or Demo license.
  - Confidence: HIGH — this is exactly what `MCPError` does.
  - Blind spot: Host UIs vary in how they surface JSON-RPC errors.
- **Decision**: FIXED — Fixed via Fix A

### F2 — Redirects can forward the Bearer token

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 1 HTTP client contract
- **Detail**: `httpx` follows redirects by default, so a 301/302 from the configured base URL can replay the Authorization header to another host.
- **Fix**: Construct the client with `follow_redirects=False` and treat a redirect as `azlimits_upstream_unavailable` without logging the Location header.
- **Decision**: FIXED

### F3 — Phase 2 test harness is still a choice

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 adapter tests
- **Detail**: "Official SDK test mechanism" maps to in-memory `Client(mcp)`, which needs an async pytest plugin. The repo has neither configured.
- **Fix**: Name one harness — `Client(mcp)` plus `anyio` / `@pytest.mark.anyio`.
- **Decision**: FIXED

### F4 — Timeout duration is unspecified

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 1 client timeout
- **Detail**: "Bounded timeout" was required without a value.
- **Fix**: Pin `httpx.Timeout(10.0)` for connect and read.
- **Decision**: FIXED
