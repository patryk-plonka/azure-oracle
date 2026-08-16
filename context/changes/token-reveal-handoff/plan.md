# Token reveal handoff Implementation Plan

## Overview

Restore the missing production handoff between one-time API-token issuance and MCP-host secret configuration. After an explicit user confirmation, `azlimits-onboard` will reveal the new raw token once on a verified interactive terminal, enabling the user to enter it into the existing host secret prompt while keeping ordinary CLI output, templates, logs, files, and process environment secret-free.

## Current State Analysis

`main.py` correctly returns the raw token only in a successful `POST /auth/tokens` response while retaining only a hash. `onboarding_cli.py` receives that value but calls its optional `completion_handoff` only when a caller injects one; the console entry point supplies none. The default completion path deliberately says the token is not displayed and renders only a VS Code `${input:azlimits-api-token}` placeholder, leaving the user unable to populate the host’s secret prompt.

`mcp_server.py` already consumes only `AZLIMITS_API_BASE_URL` and `AZLIMITS_API_TOKEN` from its own child-process environment. The MCP server, API routes, persistence model, and host template need no redesign.

## Desired End State

A developer completing interactive onboarding is warned that the new token will be shown once in their terminal and may remain in scrollback or recordings. The CLI verifies the confirmation input and designated reveal output are interactive TTYs, requires a separate affirmative reveal confirmation, then issues the token and renders it exactly once on the isolated reveal stream. The normal progress/guidance output remains token-free and continues to provide the user-level VS Code MCP configuration template.

If the user declines, cancels, or runs without both required TTYs, token issuance does not occur. If the reveal stream fails after issuance, the CLI produces only a stable non-secret recovery message, never retries token creation or re-renders the token, and explains that a new onboarding flow is required.

### Key Discoveries:

- `main.py:329-396` — token creation returns the raw value once but persists only `hash_token(raw_token)`.
- `onboarding_cli.py:172-224` — `completion_handoff` already provides an injectable raw-token seam but is not bound by `main()`.
- `onboarding_cli.py:228-272` — normal completion output and the VS Code template are intentionally secret-free and must remain so.
- `mcp_server.py:80-119` — MCP token ownership remains limited to the child-process environment.
- `tests/test_onboarding_cli.py:203-344` — existing mocked workflow and sentinel-secret tests provide the focused regression boundary.
- `AGENTS.md` — secret values must not be logged, committed, hard-coded, or persisted outside hash-only server storage.

## What We're NOT Doing

- No changes to `main.py`, API schemas, token hashing/storage, database migrations, OAuth, EULA, or token lifecycle rules.
- No changes to `mcp_server.py`, MCP tool parameters, MCP authentication, or MCP onboarding.
- No token persistence in files, `.env` files, registry, shell history, clipboard, password manager, VS Code settings, or user environment variables.
- No `setx`, generated PowerShell scripts, workspace configuration, parent-process mutation, host automation, or direct VS Code secret-store integration.
- No automatic retry of `POST /auth/tokens`, token reveal output, or any state-changing request.
- No attempt to claim that terminal display is universally private; terminal scrollback, recordings, remote sessions, and screen sharing remain user-managed exposure risks.

## Implementation Approach

Treat one-time exposure as a dedicated, production-bound completion handoff—not as a modification to generic `output` or secret-free `_print_completion` guidance. Before issuing the token, collect a second affirmative confirmation and verify that both the confirmation input and selected token reveal stream identify as TTYs. On confirmation, call the existing token endpoint once and write the raw token once through the isolated stream; continue ordinary safe completion guidance afterward.

Keep the interactive-terminal/reveal behavior injectable for deterministic tests. Tests must distinguish the intentionally confidential reveal stream from the generic normal-output collector and prove all rejected/cancelled paths occur before token issuance.

## Critical Implementation Details

TTY eligibility and explicit reveal consent must be checked after EULA acceptance and token-name selection but **before** `POST /auth/tokens`. Once a successful API response has arrived, the raw value cannot be recovered; a later stream failure cannot trigger a token or display retry. The isolated reveal path must never interpolate the raw token into exception text or pass it to the generic `output` callback.

## Phase 1: Guarded One-Time Reveal Boundary

### Overview

Bind the existing completion seam to a production-only, explicitly approved terminal reveal while preserving the existing secret-free completion output and one-time token semantics.

### Changes Required:

#### 1. Terminal eligibility, consent, and reveal collaborator

**File**: `onboarding_cli.py`

**Intent**: Add a narrowly scoped interactive completion handoff that is usable for MCP setup without enabling token-bearing arguments, files, parent-process changes, or generic output capture.

**Contract**:

- Define an injectable terminal/reveal boundary that can determine whether confirmation input and the exact token destination are TTYs, can collect a distinct affirmative reveal confirmation, and can write/flush the raw token only through the verified reveal stream.
- After EULA acceptance and non-empty token-name selection, require both TTY checks and explicit reveal consent before calling `OnboardingApiClient.create_token`. Warn that terminal scrollback, recordings, or screen sharing can retain the displayed value and direct the user to enter it immediately into the MCP host’s hidden secret prompt/store.
- If the reveal is declined, cancelled, reaches EOF, or either required stream is noninteractive, exit safely before token issuance; emit only non-secret status/recovery text.
- Bind the production reveal collaborator from `main()` so the normal `azlimits-onboard` command no longer discards the successful one-time token response.
- Preserve the generic `output` callback and `_print_completion` as secret-free paths: their progress, JSON template, exceptions, and recovery messages must never contain raw token, onboarding credential, or issuance credential.
- If reveal writing/flushing fails after successful issuance, catch the failure at the reveal boundary, do not write the token again or retry token creation, and return only a stable recovery message explaining that the one-time token may have been issued but cannot be recovered by this command.

### Success Criteria:

#### Automated Verification:

- Focused guarded-reveal workflow tests pass: `uv run pytest tests/test_onboarding_cli.py -v`
- Existing onboarding/auth and logging regressions pass: `uv run pytest tests/test_auth_oauth.py tests/test_onboarding.py tests/test_auth_token.py tests/test_logging_middleware.py -v`
- Full regression suite passes: `uv run pytest tests/ -v`
- Linting passes: `uv run ruff check .`
- Type checking passes: `uv run mypy .`

#### Manual Verification:

- In a real interactive terminal, complete onboarding with a disposable identity/token name, accept the separate reveal warning, and confirm the raw token appears once only after issuance.
- Decline the reveal confirmation in a separate disposable run and confirm no token is issued.
- Run the command with input or reveal output redirected and confirm it refuses before token issuance without exposing a token.

**Implementation Note**: After completing this phase and all automated verification passes, pause for human confirmation that the one-time reveal behavior and terminal guard are acceptable before proceeding.

---

## Phase 2: Handoff Regression Coverage and Operating Guide

### Overview

Lock the reveal contract with sentinel-secret tests and update operator documentation so the CLI’s one permitted delivery path, host configuration boundary, and recovery behavior are unambiguous.

### Changes Required:

#### 1. Reveal isolation and failure-path tests

**File**: `tests/test_onboarding_cli.py`

**Intent**: Prove that the only token-bearing channel is the explicitly injected, TTY-validated one-time reveal stream, while ordinary output and all non-success paths remain secret-free.

**Contract**:

- Extend the `respx`-mocked workflow using fake interactive/noninteractive terminal collaborators and the existing sentinel credentials/token.
- Cover successful explicit confirmation: exactly one token request, exactly one raw-token reveal write on the dedicated reveal stream, and no raw token in generic output, safe errors, or completion guidance.
- Cover reveal decline, EOF, `KeyboardInterrupt`, non-TTY confirmation input, and non-TTY reveal stream. Each must avoid `POST /auth/tokens` and avoid raw-token output.
- Cover a reveal writer/flush failure after successful issuance: no token-bearing exception text, no second reveal write, no issuance retry, and stable restart/recovery instruction.
- Retain coverage proving no files, persistent environment, registry, shell mutation, token-bearing configuration, or MCP-token parameter are introduced. Keep existing EULA/token POST no-retry behavior intact.

#### 2. Supported one-time transfer documentation

**File**: `README.md`

**Intent**: Replace the contradictory “never displays” claim with accurate, security-conscious instructions for the approved interactive reveal and existing VS Code user-level secret input.

**Contract**:

- Document the separate reveal confirmation, interactive-TTY requirement, single display, and immediate transfer to an MCP host’s hidden secret prompt/store.
- State the user-managed terminal exposure risks (scrollback, recording, remote sessions, or screen sharing) and preserve the requirement not to put tokens in command arguments, shell history, tool calls, logs, committed files, `.env` files, generated scripts, or workspace configuration.
- Document safe rejection/failure behavior: no token is issued if confirmation or terminal eligibility fails; after a post-issuance reveal failure, do not retry and restart onboarding because the raw value cannot be recovered.
- Retain the secret-free VS Code **user-level** template, `${input:azlimits-api-token}` reference, host-neutral child-process contract, and statement that the CLI cannot configure an already-running shell or editor.

### Success Criteria:

#### Automated Verification:

- Full CLI reveal and documentation tests pass: `uv run pytest tests/test_onboarding_cli.py -v`
- MCP regression tests pass: `uv run pytest tests/test_mcp_server.py -v`
- Logging secret-regression tests pass: `uv run pytest tests/test_logging_middleware.py -v`
- Full regression suite passes: `uv run pytest tests/ -v`
- Linting passes: `uv run ruff check .`
- Type checking passes: `uv run mypy .`

#### Manual Verification:

- From a clean/test VS Code profile, use the documented user-level MCP template, transfer a disposable revealed token into the hidden secret prompt/store, and confirm `search_limitations` starts without `DATABASE_URL`, OAuth credentials, or a database connection in the MCP process.
- Verify no token-bearing command, `.ps1`, `.env`, token file, registry value, or workspace configuration file is created; separately opened PowerShell/VS Code instances remain unconfigured.
- Configure an invalid/expired test token and confirm `search_limitations` returns only `azlimits_authentication_error` without the token or upstream response detail.
- Review the terminal transcript and generic CLI output path: the raw token must appear only in the approved single reveal, never in normal status/guidance/errors.

**Implementation Note**: After completing this phase and all automated verification passes, pause for human confirmation that the VS Code handoff and negative safety checks succeeded before considering the change ready for implementation review.

---

## Testing Strategy

### Unit Tests:

- Explicit reveal confirmation accepts only affirmative input and handles EOF/interrupt as pre-issuance cancellation.
- Both confirmation input and reveal output must be TTYs before token issuance.
- A successful flow writes the raw token exactly once to the isolated reveal sink and never through generic output.
- Reveal sink failures remain non-disclosing and never cause token or output retries.

### Integration Tests:

- `respx`-mocked full onboarding journey verifies EULA and issuance headers/payloads remain unchanged, the token POST occurs only after reveal preconditions pass, and raw sentinel absence holds for all ordinary outputs/errors.
- Existing auth-token and logging tests remain the server-side evidence for one-time issuance, hash-only storage, and secret-safe logs.
- Existing MCP tests remain the integration boundary for child-environment token use; no MCP code changes are required.

### Manual Testing Steps:

1. Configure a disposable/local API, GitHub OAuth app, token hash salt, isolated identity, and clean/test VS Code profile.
2. Run `azlimits-onboard` from a real interactive terminal; complete browser consent, paste the onboarding credential into its hidden prompt, accept the EULA, name the token, read the terminal-risk warning, and explicitly approve reveal.
3. Confirm the token appears once, immediately enter it into VS Code’s hidden `azlimits-api-token` secret prompt, and verify `search_limitations` succeeds using the user-level configuration.
4. Repeat with reveal declined; verify the API receives no token creation request and no new token is available.
5. Repeat with redirected input or output; verify refusal precedes issuance and no token appears in the redirected target.
6. Inspect the repository and user environment: confirm no token-bearing files, scripts, environment variables, registry values, or workspace settings were created; open a new shell/editor to confirm no parent-process mutation.
7. Replace the host secret with an invalid/expired disposable token and verify only `azlimits_authentication_error` appears, with no secret or upstream detail.

## Performance Considerations

The feature adds only local TTY checks, one confirmation prompt, and one immediate stream write during onboarding. It adds no API requests, polling, retries, persistence, or MCP proxying.

## Migration Notes

No database, API, schema, MCP-server, or deployment migration is required. Existing raw tokens cannot be revealed or recovered; users must complete a new onboarding flow to create a new one-time token.

## References

- Frame: `context/changes/token-reveal-handoff/frame.md`
- Existing CLI: `onboarding_cli.py:172-281`
- Existing CLI tests: `tests/test_onboarding_cli.py:203-344`
- Token one-time response: `main.py:329-396`
- MCP child-environment boundary: `mcp_server.py:80-119`
- Prior CLI handoff plan: `context/changes/cli-onboarding-bootstrap/plan.md` — Phase 3
- Prior API onboarding decision: `context/archive/2026-08-06-developer-onboarding-token/plan.md`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Guarded One-Time Reveal Boundary

#### Automated

- [x] 1.1 Focused guarded-reveal workflow tests pass: `uv run pytest tests/test_onboarding_cli.py -v`
- [x] 1.2 Existing onboarding/auth and logging regressions pass: `uv run pytest tests/test_auth_oauth.py tests/test_onboarding.py tests/test_auth_token.py tests/test_logging_middleware.py -v`
- [x] 1.3 Full regression suite passes: `uv run pytest tests/ -v`
- [x] 1.4 Linting passes: `uv run ruff check .`
- [x] 1.5 Type checking passes: `uv run mypy .`

#### Manual

- [x] 1.6 Interactive terminal reveals a disposable token once after explicit approval
- [x] 1.7 Declined reveal prevents token issuance
- [x] 1.8 Redirected input or output refuses before token issuance without disclosure

### Phase 2: Handoff Regression Coverage and Operating Guide

#### Automated

- [ ] 2.1 Full CLI reveal and documentation tests pass: `uv run pytest tests/test_onboarding_cli.py -v`
- [ ] 2.2 MCP regression tests pass: `uv run pytest tests/test_mcp_server.py -v`
- [ ] 2.3 Logging secret-regression tests pass: `uv run pytest tests/test_logging_middleware.py -v`
- [ ] 2.4 Full regression suite passes: `uv run pytest tests/ -v`
- [ ] 2.5 Linting passes: `uv run ruff check .`
- [ ] 2.6 Type checking passes: `uv run mypy .`

#### Manual

- [ ] 2.7 VS Code user-level secret handoff starts credential-free MCP server
- [ ] 2.8 No token-bearing artifacts or parent-process configuration are created
- [ ] 2.9 Invalid MCP token yields stable secret-free authentication failure
- [ ] 2.10 Raw token appears only in the approved single reveal
