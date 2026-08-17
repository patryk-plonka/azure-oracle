# CLI Onboarding Bootstrap Implementation Plan

## Overview

Add a local `azlimits-onboard` console command that bridges the existing browser-based developer onboarding flow to a separately configured MCP host. The command opens the existing API login route, collects the callback's short-lived onboarding credential through a hidden interactive prompt, presents the served EULA for explicit acceptance, creates a named API token through the existing REST contract, and then provides secret-free MCP-host configuration guidance.

The command is an API client and user-interaction boundary only. It does not alter OAuth callback behavior, store raw credentials, modify the caller's shell, or expand the MCP server's token-only REST adapter scope.

## Current State Analysis

`main.py` owns the complete identity and token lifecycle: `/auth/login` starts browser OAuth, `/auth/callback` returns a short-lived onboarding credential in JSON, `/auth/eula` returns versioned terms, `/auth/eula/accept` consumes onboarding credentials and issues a short-lived issuance credential, and `/auth/tokens` returns the raw API token once. `schemas.py` already provides typed models for each response. The callbacks and grants are intentionally single-use and purpose-bound.

`mcp_server.py` remains a separate stdio process that reads only `AZLIMITS_API_BASE_URL` and `AZLIMITS_API_TOKEN` from its own environment. The caller-shell boundary is non-negotiable: an executable cannot update the environment of an already-running PowerShell, VS Code, or later host process. Current documentation deliberately requires manual credential transfer and host configuration.

## Desired End State

A developer runs `azlimits-onboard --api-base-url <URL>`, approves the existing GitHub OAuth request in their browser, pastes the callback's onboarding credential at a non-echoing prompt, reviews and explicitly accepts the current EULA, and receives confirmation that a named 90-day API token was created. The CLI never reveals the raw token through normal output, error text, logs, command arguments, a generated script, an environment file, or persistent user environment settings.

At completion, the CLI gives a token-free VS Code user-level MCP configuration template using a hidden secret input and a host-neutral statement of the two required environment settings and stdio command. A developer enters the raw token only into their chosen host's approved secret prompt/store; the MCP server receives it only in its own process environment. The API and MCP server remain unchanged.

### Key Discoveries:

- `main.py:189-264` — browser OAuth returns the onboarding credential as a JSON callback response; no CLI loopback handoff, polling endpoint, or redirect relay exists.
- `main.py:267-396` — EULA acceptance and token issuance consume distinct, short-lived, single-use Bearer credentials, so state-changing requests must never be automatically retried.
- `schemas.py:40-82` — existing Pydantic response models provide the typed REST client contract for every CLI transition.
- `mcp_server.py:80-110` — the MCP process intentionally consumes only `AZLIMITS_API_BASE_URL` and `AZLIMITS_API_TOKEN`; it must not absorb onboarding or token lifecycle behavior.
- `README.md:47-49,60-62,93-96` and `AGENTS.md` — raw tokens and intermediate credentials must not be printed, logged, committed, or placed in shell history.
- `tests/test_mcp_server.py` and `tests/test_logging_middleware.py` establish mocked HTTP and sentinel-secret absence patterns that the CLI tests should reuse.

## What We're NOT Doing

- No changes to `main.py`, `auth.py`, `schemas.py`, models, migrations, OAuth callback URL, token hashing, EULA server behavior, or per-request Demo-license enforcement.
- No automatic browser-to-CLI callback capture, local listener, callback redirect, polling endpoint, device-code flow, browser automation, or distribution of the GitHub OAuth client secret. A fully automatic handoff needs a separately framed API security change.
- No direct database access, direct token generation, or duplicate authorization logic in the CLI.
- No changes to `mcp_server.py`, new MCP tools, interactive OAuth inside MCP, token tool parameters, or credential persistence in the MCP module.
- No token-bearing PowerShell commands, `setx`, registry writes, generated `.ps1`/`.env` files, output files, or automatic caller-shell/VS Code configuration. The CLI cannot mutate parent-process environments.
- No automatic retry of EULA acceptance or token creation, no caching/persisting intermediate credentials, and no live GitHub/browser/VS Code E2E automation.

## Implementation Approach

Introduce a root-level `onboarding_cli.py` module and expose it through `pyproject.toml` as `azlimits-onboard`. Keep its REST client, interactive I/O, browser opener, and configuration guidance separable so tests can replace external effects. Reuse `httpx` with fixed timeouts, disabled redirect following for all Bearer-bearing requests, and the existing Pydantic response models for successful payload validation.

The CLI validates its supplied base URL before browser launch: HTTPS is required for remote origins, while `http` is allowed only for IP-literal or named loopback development origins. It opens `/auth/login` in the default browser, asks the user to paste only the callback onboarding credential using a non-echoing prompt, fetches the EULA, requires explicit affirmative acceptance, then submits the API-returned version and the user-selected token name through the existing endpoint sequence. It emits only non-secret progress and recovery guidance; completion documentation directs the user to provide the raw token to an approved MCP-host secret mechanism.

## Critical Implementation Details

A successful state-changing request can consume its associated credential even if a transport failure prevents the CLI from receiving the response. Never auto-retry `POST /auth/eula/accept` or `POST /auth/tokens`; report a safe failure and instruct the user to restart onboarding. Only the server-selected EULA version may be submitted, and declining terms must exit before the acceptance request.

Ordinary stdout/stderr is not a secret channel. The raw token must be confined to the in-memory control path from validated token response to the selected completion boundary; it must never be interpolated into exceptions, status messages, logs, templates, or persistent artifacts. The VS Code template must contain only `${input:...}` reference syntax, not the token value.

## Phase 1: Console Command and Safe REST Client

### Overview

Create the independently testable console command foundation: argument parsing, API base-URL validation, browser launch, typed REST client methods, and stable non-secret CLI error handling.

### Changes Required:

#### 1. Console entry point and dependency metadata

**File**: `pyproject.toml`

**Intent**: Register a supported console command without adding a CLI framework or a new runtime dependency; the standard library and existing `httpx` dependency are sufficient.

**Contract**: Add a `[project.scripts]` entry that resolves `azlimits-onboard` to `onboarding_cli:main`. Retain the existing Python 3.12 runtime floor and dependencies; regenerate `uv.lock` only if package metadata changes require it.

#### 2. Local onboarding client module

**File**: `onboarding_cli.py` (new)

**Intent**: Provide a narrow, reusable client boundary for the existing onboarding REST API, keeping URL validation, browser launch, successful-response validation, and safe failures out of the interactive workflow implementation.

**Contract**:

- Parse a required API base URL and optional token name input without accepting tokens, onboarding credentials, issuance credentials, OAuth state, or client secrets as command-line arguments or environment configuration.
- Accept `https` origins for remote servers and `http` only for loopback development hosts (`localhost`, `127.0.0.1`, or `::1`); reject URLs lacking a host, containing query/fragment/userinfo, or having other cleartext remote origins before the browser opens or an HTTP request is made.
- Build fixed endpoint paths `/auth/login`, `/auth/eula`, `/auth/eula/accept`, and `/auth/tokens` from a normalized base URL. Open only `/auth/login` with an injectable standard-library browser opener.
- Provide typed methods for EULA retrieval, EULA acceptance, and token issuance. Use `httpx.Timeout(10.0)`, `follow_redirects=False`, Bearer authorization only in request headers, and `OAuthCallbackResponse`-adjacent input validation plus existing `EulaDocumentResponse`, `EulaAcceptanceResponse`, and `TokenCreateResponse` models for successful server payloads.
- Map malformed success payloads, redirects, non-success statuses, and transport failures to concise CLI-safe failures that exclude credentials, authorization values, response bodies, response headers, redirect locations, and full user-supplied URL details.
- Keep the module free of FastAPI, ORM, database, MCP-server, and persistent-secret-store dependencies. It must not log or print the credential values it receives.

#### 3. Focused client and entry-point tests

**File**: `tests/test_onboarding_cli.py` (new)

**Intent**: Establish a non-DB test boundary for base URL policy, browser initiation, REST request composition, typed response handling, and safe failures before wiring the full interactive sequence.

**Contract**: Use `pytest`, `respx`, and injected browser/I/O collaborators. Assert that loopback HTTP and remote HTTPS are accepted, remote HTTP and malformed origins are rejected pre-effect, and the browser target is exactly `<base>/auth/login`. Assert successful REST methods use exact endpoint, expected Bearer header, expected payload, `httpx.Timeout(10.0)`, and disabled redirects. Use sentinel credentials and server bodies to prove all safe errors omit secrets and untrusted upstream details; tests must not import `main.py`, contact GitHub, start a browser, connect to Postgres, or start an MCP host.

### Success Criteria:

#### Automated Verification:

- Focused CLI tests pass: `uv run pytest tests/test_onboarding_cli.py -v`
- Relevant auth/MCP regression tests pass: `uv run pytest tests/test_auth_oauth.py tests/test_onboarding.py tests/test_auth_token.py tests/test_mcp_server.py -v`
- Full regression suite passes: `uv run pytest tests/ -v`
- Linting passes: `uv run ruff check .`
- Type checking passes: `uv run mypy .`

#### Manual Verification:

- Run `azlimits-onboard --help` and confirm it asks only for non-secret configuration/metadata, not bearer credentials or OAuth secrets.
- Invoke the command once with a malformed and once with a remote HTTP base URL; confirm it fails before launching a browser and does not echo the full rejected value.
- Review the CLI module and test output paths to confirm no logger, exception, or normal status message formats a credential or token.

**Implementation Note**: After completing this phase and all automated verification passes, pause for human confirmation that the command boundary and transport policy are acceptable before proceeding.

---

## Phase 2: Explicit Interactive Onboarding Workflow

### Overview

Implement the interactive browser-to-token sequence on top of the Phase 1 client, preserving browser consent, explicit EULA acceptance, one-time credential semantics, and raw-token containment.

### Changes Required:

#### 1. Interactive workflow orchestration

**File**: `onboarding_cli.py`

**Intent**: Turn the safe REST client into an operator-friendly onboarding workflow that eliminates manual HTTP calls while retaining the existing browser callback and consent boundaries.

**Contract**:

- Launch the validated API login URL in the default browser and clearly instruct the user to finish GitHub consent and paste only the returned onboarding credential into a non-echoing interactive prompt. Do not scrape browser content, bind a listener, accept credentials over command arguments/stdin pipelines, or persist the pasted value.
- Fetch the current EULA with the onboarding Bearer credential, render the exact returned content and version, then require an explicit affirmative confirmation. A decline, empty response, interrupt, or cancellation exits cleanly without calling EULA acceptance or token issuance.
- Submit the exact version returned from EULA retrieval to `/auth/eula/accept`; then collect a non-empty token name through interactive input and submit it only to `/auth/tokens` with the issuance Bearer credential.
- Treat `401`, `403`, `409`, redirects, malformed payloads, timeouts, and transport failures as safe actionable failures. Never auto-retry either state-changing POST, even after a timeout or 5xx; explain that the user must restart the onboarding flow because the credential may already have been consumed.
- Keep the raw API token in memory only. Normal completion output may confirm the created token name and expiry but must not reveal the token, token ID, onboarding credential, or issuance credential. Pass the raw token only to the narrowly defined completion-handoff collaborator in the same process.

#### 2. Workflow behavior and secret-containment tests

**File**: `tests/test_onboarding_cli.py`

**Intent**: Prove the full client-side sequence uses each existing API handoff correctly and cannot leak secrets or silently bypass consent.

**Contract**: Add fully mocked scenarios for:

- browser launch followed by hidden onboarding-credential entry, EULA fetch, affirmative acceptance using the served version, named token request, and one-time completion handoff;
- user decline/cancellation before EULA acceptance, proving neither state-changing endpoint is called;
- wrong/expired credential, version conflict, redirect, malformed payload, timeout, and upstream failure paths, proving no state-changing automatic retry occurs;
- exact separation of onboarding and issuance Bearer headers and token-name JSON payload;
- sentinel onboarding credential, issuance credential, and raw API token absence from normal output, captured errors, and logs;
- no local callback listener, callback/poll endpoint, persistent token artifact, `setx`, registry update, or shell-environment mutation is invoked.

Retain existing server onboarding/auth tests as regression evidence rather than duplicating server state-machine testing in the CLI suite.

### Success Criteria:

#### Automated Verification:

- Full focused CLI workflow tests pass: `uv run pytest tests/test_onboarding_cli.py -v`
- Existing onboarding and secret-logging tests pass: `uv run pytest tests/test_auth_oauth.py tests/test_onboarding.py tests/test_auth_token.py tests/test_logging_middleware.py -v`
- Full regression suite passes: `uv run pytest tests/ -v`
- Linting passes: `uv run ruff check .`
- Type checking passes: `uv run mypy .`

#### Manual Verification:

- Against a disposable/local API and GitHub OAuth application, complete browser consent, copy the callback credential into the hidden prompt, inspect the displayed EULA, and decline it; confirm the server does not issue a token or Demo entitlement through the CLI path.
- Repeat onboarding, explicitly accept the displayed current EULA, enter a token name, and confirm the CLI reports only non-secret completion metadata.
- Simulate an interruption after EULA acceptance or token issuance and confirm the CLI directs the user to restart rather than retrying the POST with a potentially consumed credential.

**Implementation Note**: After completing this phase and all automated verification passes, pause for human confirmation that the explicit-consent and one-time-credential experience is understandable before proceeding.

---

## Phase 3: MCP-Host Handoff Documentation and Final Verification

### Overview

Provide a safe, concrete completion path for configuring the existing local MCP server while making the caller-shell limitation and host-specific secret responsibility explicit.

### Changes Required:

#### 1. Secret-free completion guidance

**File**: `onboarding_cli.py`

**Intent**: Give developers useful next steps after successful token issuance without exposing the raw token in a reusable command, file, or ordinary terminal output.

**Contract**:

- Use the raw token only while presenting a private, interactive completion boundary appropriate to the chosen host; do not render it as a PowerShell assignment, JSON value, or configuration-file value.
- Present a secret-free VS Code **user-level** MCP configuration template that references a password-style input variable for `AZLIMITS_API_TOKEN`, includes `AZLIMITS_API_BASE_URL`, and launches `uv run python mcp_server.py` from the repository directory. The template must contain placeholders/input references only.
- State that the user must enter the one-time token directly into the host’s approved hidden secret prompt/store, not shell history, a tool call, a committed workspace file, a `.env` file, or normal terminal input. Do not claim interactive-input support is universal across all MCP hosts.
- Provide host-neutral requirements for other MCP hosts: launch the existing local stdio command and supply only `AZLIMITS_API_BASE_URL` plus the raw API token from an approved secret mechanism to the MCP child process. Explicitly state that the standalone CLI cannot configure an already-running PowerShell, VS Code, or other parent process.

#### 2. README onboarding and host-configuration guide

**File**: `README.md`

**Intent**: Replace the manual multi-request onboarding instructions with the supported CLI path while preserving a safe explanation of the current browser callback and MCP configuration constraints.

**Contract**:

- Document console-command installation/use through the existing `uv` workflow, the accepted API base URL rule, browser consent step, hidden onboarding-credential prompt, explicit EULA confirmation, token-name prompt, and no-auto-retry/restart behavior.
- Explain that the browser callback still exposes an onboarding credential and that the initial CLI release requires a deliberate copy into the hidden prompt; do not claim fully automatic callback capture.
- Document VS Code user-level MCP configuration as an illustrative secret-free template; state the user enters the raw token only via the host’s hidden secret facility. Give host-neutral requirements for other MCP hosts and explicitly distinguish them from source-controlled workspace settings.
- Remove guidance that encourages users to paste raw tokens into PowerShell environment assignments. Retain the invariant that the MCP server itself needs only `AZLIMITS_API_BASE_URL` and `AZLIMITS_API_TOKEN` and does not need database/OAuth configuration.
- Retain stable MCP failure-class documentation and add the CLI’s safe recovery expectations without including real or placeholder-looking token values that could be mistaken for usable credentials.

#### 3. Documentation and completion-output tests

**File**: `tests/test_onboarding_cli.py`

**Intent**: Lock the secret-free handoff contract so later usability changes do not regress into raw-token printing or token-bearing configuration artifacts.

**Contract**: Test that completion guidance/template output contains the MCP command, base-URL variable, token-variable/input reference, and no sentinel raw token. Test that no persistent environment, registry, token file, or caller-shell mutation operation is requested. Cover safe behavior when host guidance is displayed after successful issuance, while treating actual VS Code secret storage and host startup as manual-only integration checks.

### Success Criteria:

#### Automated Verification:

- CLI handoff and documentation-focused tests pass: `uv run pytest tests/test_onboarding_cli.py -v`
- MCP regression tests pass: `uv run pytest tests/test_mcp_server.py -v`
- Full regression suite passes: `uv run pytest tests/ -v`
- Linting passes: `uv run ruff check .`
- Type checking passes: `uv run mypy .`

#### Manual Verification:

- From a clean VS Code user profile or test profile, add the documented user-level configuration with a placeholder/input reference, enter a disposable token only through the host’s hidden prompt/store, and confirm the existing `search_limitations` tool discovers and runs without `DATABASE_URL`, OAuth credentials, or a database connection in the MCP process.
- Confirm the generated/documented template has no raw token and that no token-bearing command, `.ps1`, `.env`, or workspace configuration file is created by the CLI.
- With an invalid/expired configured token, invoke `search_limitations` and confirm the stable authentication failure contains neither a token nor upstream response details.
- Confirm an independently started PowerShell/VS Code instance remains unconfigured after CLI completion, demonstrating that the documentation does not overpromise parent-process mutation.

**Implementation Note**: After completing this phase and all automated verification passes, pause for human confirmation that the host setup is both usable and secret-safe before considering the change ready for implementation review.

---

## Testing Strategy

### Unit Tests:

- API base URL normalization and transport policy: remote HTTPS and loopback HTTP accepted; remote HTTP, malformed URLs, query/fragment/userinfo rejected before effects.
- Exact endpoint construction, browser-login URL generation, headers, body shape, timeout, disabled redirects, and Pydantic validation for each REST transition.
- EULA confirmation behavior: exact content/version display, affirmative-only acceptance, no side effects after decline/cancel.
- Safe failure mapping for response errors, redirects, malformed JSON, timeouts, and transport errors.
- Completion guidance content, including absence of sentinel raw token and no persistent/caller-shell mutation API.

### Integration Tests:

- `respx`-mocked onboarding sequence verifies browser-to-hidden-prompt handoff, onboarding-to-issuance header transition, EULA-version continuity, token-name payload, and one-time completion boundary.
- Sentinel-secret regression asserts onboarding credential, issuance credential, raw API token, and response-body sentinel are absent from normal output, safe errors, and captured logs.
- Existing FastAPI onboarding/auth tests and MCP tests remain the integration coverage for the server-side state machine and stdio process contract.

### Manual Testing Steps:

1. Configure a local/disposable API with its required database, OAuth credentials, callback URL, and token hash salt; use an isolated test identity.
2. Run `azlimits-onboard --api-base-url http://localhost:8000`, approve GitHub consent, and copy the browser callback onboarding credential only into the hidden prompt.
3. Read the EULA rendered by the CLI, first decline it and verify no token is created, then repeat and affirm acceptance with a non-sensitive test token name.
4. Confirm CLI terminal output never shows the raw token; enter it only into the MCP host’s approved hidden secret mechanism.
5. Apply the documented **user-level** MCP configuration, start the local stdio server through the host, and call `search_limitations`.
6. Restart or use a separately opened PowerShell/VS Code instance and verify it was not automatically configured by the CLI.
7. Use an invalid/expired MCP token and verify the tool returns only its stable authentication failure class.

## Performance Considerations

The CLI runs only during onboarding and makes at most three authenticated API requests after browser consent. Use a bounded 10-second request timeout and no automatic retry for state-changing calls. It must not introduce polling, a long-running callback listener, browser automation, or an MCP proxy process.

## Migration Notes

No data migration, database change, API-route change, MCP-server change, or user-token migration is required. The `pyproject.toml` console-script metadata exposes the new module through the existing `uv` environment; any lockfile update remains a normal metadata synchronization step.

## References

- Frame: `context/changes/cli-onboarding-bootstrap/frame.md`
- Product requirements: `context/foundation/prd.md` — US-01, US-02, FR-001 through FR-006, FR-007
- Existing REST onboarding lifecycle: `main.py:189-396`
- Typed response models: `schemas.py:40-82`
- Existing MCP boundary: `mcp_server.py:80-177`
- API onboarding tests: `tests/test_auth_oauth.py`, `tests/test_onboarding.py`, `tests/test_auth_token.py`
- Secret/logging test patterns: `tests/test_logging_middleware.py`, `tests/test_mcp_server.py`
- Test risk map: `context/foundation/test-plan.md` — Risks #3 and #4
- Prior onboarding decision: `context/archive/2026-08-06-developer-onboarding-token/plan-brief.md`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Console Command and Safe REST Client

#### Automated

- [x] 1.1 Focused CLI tests pass: `uv run pytest tests/test_onboarding_cli.py -v` — 82bb841
- [x] 1.2 Relevant auth/MCP regression tests pass: `uv run pytest tests/test_auth_oauth.py tests/test_onboarding.py tests/test_auth_token.py tests/test_mcp_server.py -v` — 82bb841
- [x] 1.3 Full regression suite passes: `uv run pytest tests/ -v` — 82bb841
- [x] 1.4 Linting passes: `uv run ruff check .` — 82bb841
- [x] 1.5 Type checking passes: `uv run mypy .` — 82bb841

#### Manual

- [x] 1.6 CLI help exposes no bearer credential or OAuth-secret argument — 82bb841
- [x] 1.7 Malformed and remote HTTP base URLs fail before browser launch without echoing values — 82bb841
- [x] 1.8 CLI source/output review confirms no credential logging or formatting — 82bb841

### Phase 2: Explicit Interactive Onboarding Workflow

#### Automated

- [x] 2.1 Full focused CLI workflow tests pass: `uv run pytest tests/test_onboarding_cli.py -v` — b3cc97c
- [x] 2.2 Existing onboarding and secret-logging tests pass: `uv run pytest tests/test_auth_oauth.py tests/test_onboarding.py tests/test_auth_token.py tests/test_logging_middleware.py -v` — b3cc97c
- [x] 2.3 Full regression suite passes: `uv run pytest tests/ -v` — b3cc97c
- [x] 2.4 Linting passes: `uv run ruff check .` — b3cc97c
- [x] 2.5 Type checking passes: `uv run mypy .` — b3cc97c

#### Manual

- [x] 2.6 Browser consent followed by declined EULA causes no CLI-driven token/entitlement issuance — b3cc97c
- [x] 2.7 Accepted EULA creates a named token while CLI reveals only non-secret completion metadata — b3cc97c
- [x] 2.8 Interrupted state-changing request instructs restart rather than automatic retry — b3cc97c

### Phase 3: MCP-Host Handoff Documentation and Final Verification

#### Automated

- [x] 3.1 CLI handoff and documentation-focused tests pass: `uv run pytest tests/test_onboarding_cli.py -v`
- [x] 3.2 MCP regression tests pass: `uv run pytest tests/test_mcp_server.py -v`
- [x] 3.3 Full regression suite passes: `uv run pytest tests/ -v`
- [x] 3.4 Linting passes: `uv run ruff check .`
- [x] 3.5 Type checking passes: `uv run mypy .`

#### Manual

- [x] 3.6 VS Code user-level secret configuration starts and calls credential-free MCP server
- [x] 3.7 No token-bearing command, script, env file, or workspace configuration is created
- [x] 3.8 Invalid MCP token yields stable secret-free authentication failure
- [x] 3.9 Independently started parent shell/editor remains unconfigured after CLI completion
