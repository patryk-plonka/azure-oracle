# Frame Brief: CLI Onboarding Bootstrap

> Framing step before `/10x-plan`. This document captures what is *actually*
> at issue, separated from what was initially assumed.

## Reported Observation

The full developer onboarding and MCP setup sequence is too manual: a developer must open browser OAuth, relay short-lived credentials through EULA acceptance and token issuance, then configure the local MCP process.

## Initial Framing (preserved)

- **User's stated cause or approach**: Add a CLI that launches the existing browser-based OAuth flow, collects the onboarding credential, completes token issuance, and adds the token to an environment variable.
- **User's proposed direction**: Automate requesting an API token and set it only for the current shell.
- **Pre-dispatch narrowing**: The full onboarding sequence is too manual.

## Dimension Map

The observation could originate at any of these dimensions:

1. **OAuth browser-to-client handoff** — the API callback delivers the onboarding credential as JSON in a browser-owned interaction, rather than to a local client flow.
2. **Credential progression** — onboarding, EULA acceptance, and token issuance intentionally use purpose-bound, short-lived, single-use credentials. ← initial framing
3. **MCP credential ownership** — the MCP process is deliberately a token-only REST adapter and cannot run onboarding itself.
4. **Caller-shell configuration boundary** — a standalone child process cannot change the environment of its already-running PowerShell parent.

## Hypothesis Investigation

| Hypothesis | Evidence | Verdict |
| --- | --- | --- |
| Browser-to-client handoff lacks an automation bridge | `README.md:51-67` instructs manually relaying callback JSON; `main.py:189-264` has only an API-owned callback; no CLI, browser launcher, or loopback listener exists. | STRONG |
| Purpose-bound credential progression is the cause | `main.py:120-150`, `main.py:271-396` enforce distinct 5-minute, single-use onboarding and issuance grants; `tests/test_onboarding.py:34-44,105-111` and `tests/test_auth_token.py:41-85` cover rejection. | STRONG |
| MCP server should own or run onboarding | `mcp_server.py:80-110,154-169` reads environment values and intentionally exposes search only; `context/changes/mcp-tool-wrapper/plan.md` explicitly excludes interactive OAuth and token lifecycle. | NONE |
| CLI can configure its invoking shell directly | `README.md:86-96` documents manual session-local PowerShell assignments; no caller-shell bridge exists. A child process cannot mutate its parent environment. | STRONG |

## Narrowing Signals

- The leading concern is the full manual onboarding sequence, not only the OAuth callback or only MCP configuration.
- The raw API token is returned once and must not be printed, logged, committed, or placed in shell history (`README.md:60-62,93-96`).
- Existing automated coverage models credential handoffs as API requests, while MCP tests inject configuration externally (`tests/test_onboarding.py:111-157`, `tests/test_mcp_server.py:51-115`).

## Cross-System Convention

The completed onboarding change deliberately provided a JSON/OpenAPI workflow without a CLI (`context/archive/2026-08-06-developer-onboarding-token/plan-brief.md`, “What & Why” / “Out of scope”). The completed MCP wrapper deliberately remains a thin stdio adapter with per-developer environment settings (`context/changes/mcp-tool-wrapper/plan-brief.md`, “Credential ownership” / “Scope”). This confirms the missing layer is local developer bootstrap orchestration, not missing API authorization or MCP capabilities.

## Reframed (or Confirmed) Problem Statement

> **The actual problem to plan around is**: Add a safe local developer-bootstrap boundary that bridges the existing interactive, consent-based REST onboarding flow to a separately configured MCP process, without expanding the MCP server or claiming to mutate the invoking shell.

The existing OAuth, EULA, token issuance, token hashing, and MCP request paths are intentional product boundaries. The CLI should orchestrate the client-side handoffs while preserving browser consent, explicit EULA acceptance, single-use credentials, one-time token handling, and the MCP server’s credential-free design. A current-shell-only outcome requires a caller-mediated interface or a launched child process; a standalone executable cannot set the parent PowerShell environment after it exits.

## Confidence

- **HIGH** — direct source and test evidence establishes the intended API/MCP separation, and an independent check reached the same bootstrap-boundary conclusion.

## What Changes for `/10x-plan`

Plan a standalone local onboarding/bootstrap client around the existing REST contract, browser consent, explicit EULA confirmation, safe one-time token handling, and an explicit MCP-host or caller-mediated configuration boundary. Do not plan OAuth, token issuance, database access, or secret-bearing MCP tools inside `mcp_server.py`.

## References

- Source files: `README.md:35-117`; `main.py:120-410`; `mcp_server.py:80-110,154-169`; `schemas.py:40-82`; `tests/test_onboarding.py:34-165`; `tests/test_auth_token.py:41-108`; `tests/test_mcp_server.py:51-115`.
- Related prior decisions: `context/archive/2026-08-06-developer-onboarding-token/plan-brief.md`; `context/changes/mcp-tool-wrapper/plan.md`; `context/changes/mcp-tool-wrapper/plan-brief.md`.
- Investigation tasks: OAuth browser boundary; credential-flow boundary; shell/MCP boundary; independent cross-system check.
