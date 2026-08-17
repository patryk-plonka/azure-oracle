<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: CLI Onboarding Bootstrap

- **Plan**: `context/changes/cli-onboarding-bootstrap/plan.md`
- **Scope**: All completed phases (3 of 3)
- **Date**: 2026-08-17
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 4 warnings, 1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | WARNING |
| Success Criteria | PASS |

## Verification Evidence

- `uv run pytest tests/test_onboarding_cli.py -v` — 32 passed
- `uv run pytest tests/test_auth_oauth.py tests/test_onboarding.py tests/test_auth_token.py tests/test_logging_middleware.py -v` — 28 passed
- `uv run pytest tests/ -v` — 116 passed
- `uv run ruff check .` — passed
- `uv run mypy .` — passed
- Manual Phase 1–3 items are marked complete in the plan following the user's confirmation. No independent browser/MCP host execution evidence is committed.

## Findings

### F1 — Raw token uses the ordinary stdout channel

- **Severity**: ⚠️ WARNING
- **Impact**: 🔬 HIGH — architectural stakes; think carefully before deciding
- **Dimension**: Plan Adherence / Safety & Quality
- **Location**: `onboarding_cli.py:34-50, 259-268`
- **Detail**: The plan requires the raw token to pass only through a private interactive completion boundary and not through normal output. Production `main()` constructs `TerminalRevealHandoff(sys.stdin, sys.stdout)`, while the same stdout stream carries status and guidance. The token is therefore exposed to ordinary stdout capture, redirection, terminal recording, or CI logs even though it is TTY-gated.
- **Fix**: Separate the reveal destination from ordinary status output and require an explicitly private interactive destination, or revise the plan and README to accept deliberate one-time terminal disclosure as the supported boundary.
  - Strength: Resolves the ambiguity at the security boundary rather than relying on user warnings.
  - Tradeoff: May require a user-facing handoff redesign because the current host setup is copy-based.
  - Confidence: HIGH — the same stream is visibly used for both secret and non-secret output.
  - Blind spot: The intended host-specific secret facility is not available through the current generic CLI interface.
- **Decision**: FIXED — use `sys.stderr` as the dedicated reveal stream.

### F2 — Committed package metadata contains superseded unsafe onboarding guidance

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence / Pattern Consistency
- **Location**: `azure_oracle.egg-info/PKG-INFO:35-88`
- **Detail**: `README.md` now documents `azlimits-onboard` and removes token-bearing PowerShell assignments, but committed `PKG-INFO` still contains the old manual REST workflow and `$env:AZLIMITS_API_TOKEN` guidance. Package metadata can therefore contradict the current security instructions.
- **Fix**: Regenerate the committed egg-info metadata from the current project metadata, or remove generated egg-info from source control if repository policy permits.
- **Decision**: FIXED — regenerated committed setuptools metadata from the current README.

### F3 — Workflow failure matrix is not fully locked by tests

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Plan Adherence / Success Criteria
- **Location**: `tests/test_onboarding_cli.py`
- **Detail**: The plan calls for workflow coverage of redirects, malformed acceptance/token payloads, timeout and upstream failures across transitions, cancellation, and proof of no state-changing retry. Current tests cover acceptance status failures and token timeout, but do not comprehensively cover redirects, malformed acceptance/token payloads, or token redirect/upstream failures.
- **Fix**: Add mocked workflow cases for each unrepresented acceptance/token redirect, malformed payload, and upstream failure path, asserting one request and safe output.
  - Strength: Makes the explicit plan contract regression-tested.
  - Tradeoff: Adds focused test maintenance and several parametrized cases.
  - Confidence: HIGH — the missing cases are directly enumerated in the plan.
  - Blind spot: Some safety behavior is already shared through `_request_model`, reducing runtime risk.
- **Decision**: FIXED — added workflow coverage for redirect, malformed-payload, upstream-failure, and no-retry cases.

### F4 — External EULA and token metadata are not terminal-sanitized

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: `onboarding_cli.py:256-258, 281`
- **Detail**: EULA content, EULA version, and token name are written directly to the terminal. Control characters from a compromised or misconfigured API response could manipulate terminal display or conceal output.
- **Fix**: Strip or escape terminal control characters before rendering server-controlled text while preserving the content needed for EULA review.
  - Strength: Prevents terminal spoofing without changing the REST contract.
  - Tradeoff: Escaping content slightly changes how unusual EULA text is displayed.
  - Confidence: MED — terminal behavior and the acceptable EULA rendering policy need confirmation.
  - Blind spot: No current requirement defines whether control characters must be visibly escaped or rejected.
- **Decision**: FIXED — sanitize terminal control sequences from EULA and token metadata output.

### F5 — Response bodies have no explicit size bound

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: `onboarding_cli.py:158-172`
- **Detail**: The client uses a bounded timeout and closes the HTTP client, but calls `response.json()` without a response-size limit. A compromised upstream could return an excessively large body and cause avoidable memory/CPU consumption.
- **Fix**: Enforce a small maximum response body size before JSON parsing, preferably with a content-length check and bounded streaming read.
  - Strength: Adds a clear resource bound at the external API boundary.
  - Tradeoff: Requires choosing and testing a maximum size compatible with EULA content.
  - Confidence: MED — the appropriate limit depends on expected EULA size.
  - Blind spot: Current API response-size expectations are not documented.

- **Decision**: FIXED — reject responses exceeding the 1 MiB client response limit before validation.

### F6 — Timeout and redirect transport settings lack direct assertions

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: `tests/test_onboarding_cli.py:112-158`
- **Detail**: The implementation sets `httpx.Timeout(10.0)` and `follow_redirects=False`, but the focused tests do not directly assert those client settings or successful-request redirect behavior despite those being explicit plan contracts.
- **Fix**: Add a small targeted assertion or mock-client seam that verifies the timeout and disabled redirect configuration.
- **Decision**: FIXED — added direct assertions for `httpx.Timeout(10.0)` and `follow_redirects=False`.
