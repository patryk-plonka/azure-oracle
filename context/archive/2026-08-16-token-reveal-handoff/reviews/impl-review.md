<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Token reveal handoff

- **Plan**: `context/changes/token-reveal-handoff/plan.md`
- **Scope**: Full plan — Phases 1–2 of 2
- **Date**: 2026-08-17
- **Verdict**: APPROVED
- **Findings**: 0 critical, 0 warnings, 0 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | PASS |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Findings

### F1 — Injectable confirmation input is not tied to the validated TTY

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Plan Adherence
- **Location**: `onboarding_cli.py:32-58, 209-220`
- **Detail**: `TerminalRevealHandoff.is_interactive()` validates its stored confirmation stream, but `confirm()` reads from an independently supplied `input_fn`. A caller can therefore provide a TTY-looking handoff stream while the actual confirmation callback reads from a pipe, file, or automation source. The production `main()` path currently passes matching standard streams, but the injectable boundary does not enforce the planned exact-input TTY invariant. Existing non-TTY tests validate the stored fake stream rather than the callback used for confirmation.
- **Fix**: Bind confirmation reads to the validated confirmation stream, or make the handoff own and validate the confirmation function/stream instead of accepting an unrelated callback.
  - Strength: Restores the explicit “exact confirmation input” contract at the reusable boundary.
  - Tradeoff: Requires a small API/test adjustment.
  - Confidence: HIGH — directly follows the plan’s TTY contract.
  - Blind spot: The preferred callback/stream shape should be chosen before editing.
- **Decision**: FIXED — tightened the handoff so its injected confirmation callback is owned by the TTY-validated boundary; focused tests pass.

### F2 — Required no-artifact safety proof is incomplete

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Success Criteria
- **Location**: `tests/test_onboarding_cli.py:480-500`
- **Detail**: Phase 2 requires regression coverage proving that no files, persistent environment, registry, shell mutation, token-bearing configuration, or MCP-token parameter are introduced. The implementation does not perform those operations, but the added test only checks README strings and does not assert filesystem, environment, registry, process, or argument state.
- **Fix**: Add focused assertions around a successful mocked onboarding run that snapshot relevant environment/files and verify the token appears only in the dedicated reveal sink; keep registry checks limited to Windows-safe non-mutating inspection if needed.
  - Strength: Turns the plan’s explicit safety boundary into executable evidence.
  - Tradeoff: More platform-sensitive test setup and maintenance.
  - Confidence: MED — the exact artifact surface should be scoped to what the CLI can mutate.
  - Blind spot: Registry inspection semantics vary by Windows environment.
- **Decision**: FIXED — added process environment, argv, and temporary-worktree artifact assertions; focused tests pass.

### F3 — Production reveal output shares stdout with generic output

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: `onboarding_cli.py:351-359`
- **Detail**: `main()` passes `sys.stdout` both to the default generic `print` output and to `TerminalRevealHandoff`. The raw token is logically isolated from the `output` callback, but not physically isolated from ordinary stdout. This makes transcript capture and stream interleaving a property of the same OS stream, although no current generic output occurs during the reveal write.
- **Fix**: Use a clearly defined dedicated terminal destination for the reveal, or document and test that stdout is intentionally the sole terminal destination while ensuring no generic output occurs during the reveal write.
  - Strength: Makes the intended disclosure boundary explicit and testable.
  - Tradeoff: A dedicated terminal device can be platform-specific; documenting stdout preserves portability.
  - Confidence: MED — production host behavior and terminal conventions should guide the choice.
  - Blind spot: No real deployment transcript was inspected during review.
- **Decision**: FIXED — added direct production-entry-point wiring coverage.

### F4 — Production `main()` wiring lacks direct regression coverage

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: `tests/test_onboarding_cli.py` (no direct success-path `main()` test)
- **Detail**: The original defect was that the console entry point discarded the successful token response. Tests cover `run_onboarding(..., reveal_handoff=...)`, but not that `main()` still wires the production handoff. A future change could remove the binding while the workflow tests remain green.
- **Fix**: Add a narrow `main()` wiring test with monkeypatched standard streams/client effects, asserting one token request and one reveal write.
- **Decision**: FIXED — documented the intentional stdout boundary and added a regression contract keeping reveal writes out of generic output.
