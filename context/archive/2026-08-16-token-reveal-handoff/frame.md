# Frame Brief: Token reveal handoff

> Framing step before /10x-plan. This document captures what is *actually*
> at issue, separated from what was initially assumed.

## Reported Observation

`azlimits-onboard` creates a one-time raw API token but gives the user no way
to transfer it into MCP configuration, so the documented handoff cannot be
completed.

## Initial Framing (preserved)

- **User's stated cause or approach**: The missing capability is a safe one-time token reveal.
- **User's proposed direction**: Add an explicitly approved interactive reveal so the token can be copied into an MCP host's secret prompt/store.
- **Pre-dispatch narrowing**: No usable token handoff: the one-time token exists only in CLI memory, so MCP setup cannot be completed.

## Dimension Map

The observation could originate at any of these dimensions:

1. **API token response contract** — the API may fail to make the one-time raw token available to the CLI.
2. **CLI completion boundary** — the CLI may receive the value but omit a production user-mediated transfer path. ← initial framing
3. **MCP-host secret intake** — an MCP host may be unable to accept a secret supplied through the documented configuration.
4. **Secret-handling contract** — the non-disclosure rule may prohibit every usable delivery mechanism rather than only unsafe persistence and accidental exposure.

## Hypothesis Investigation

| Hypothesis | Evidence | Verdict |
| --- | --- | --- |
| API token response does not provide a raw token | `main.py:329-396` generates a raw token, persists only its hash, and returns `TokenCreateResponse(token=raw_token)`; `schemas.py:63-68` defines the field. | NONE |
| CLI completion boundary lacks a production transfer | `onboarding_cli.py:213-224` receives `TokenCreateResponse`; `onboarding_cli.py:222-223` invokes `completion_handoff` only when injected; `main.py` invokes `run_onboarding` without it. `_print_completion` suppresses the value and renders only `${input:azlimits-api-token}`. | STRONG |
| MCP host cannot consume a host-supplied token | `mcp_server.py:80-119` reads only `AZLIMITS_API_BASE_URL` and `AZLIMITS_API_TOKEN` from the child process environment; `tests/test_mcp_server.py:51-55` proves externally supplied configuration works. | NONE |
| Existing contract bars any usable one-time delivery | The archived API onboarding decision permits the token in its one successful creation response (`context/archive/2026-08-06-developer-onboarding-token/plan.md`, Desired End State). `AGENTS.md` requires hash-only persistence and no inadvertent logging/commit/return, while the active CLI plan itself calls for a private interactive completion boundary (`context/changes/cli-onboarding-bootstrap/plan.md`, Phase 3). | WEAK |

## Narrowing Signals

- The user identified the leading concern as the unusable handoff, not parent-process configuration or a generic token-storage concern.
- The API exposes the raw token precisely once and the MCP server accepts a host-supplied token, isolating the gap to CLI completion.
- The CLI has a test-only collaborator seam, but the production entry point does not bind it.

## Cross-System Convention

The prior API-first onboarding change deliberately makes the raw token available only in its one successful creation response and retains only a hash. The MCP wrapper deliberately accepts its token solely through the child process environment. The CLI should bridge those established boundaries; it must not move onboarding into `mcp_server.py`, persist the token, or mutate a parent shell/editor.

## Reframed (or Confirmed) Problem Statement

> **The actual problem to plan around is**: The CLI receives the API's one-time raw token but has no production, explicitly user-mediated confidential handoff into an MCP host's approved secret-entry boundary before the value is discarded.

The initial framing was substantially correct, but the defect is narrower than token storage or MCP configuration generally. A plan must restore the promised usable completion boundary while preserving hash-only server persistence, no parent-process mutation, and no accidental disclosure through logs, files, arguments, or configuration templates.

## Confidence

- **HIGH** — direct source inspection, tests, active-plan contract, and an independent cross-system check all identify the unbound CLI completion handoff; API issuance and MCP consumption both work as designed.

## What Changes for /10x-plan

Plan a narrowly scoped CLI completion-handoff contract that lets a consenting user transfer the one-time token into an approved MCP-host secret mechanism. Preserve the API/MCP separation and explicitly define the allowed interactive exposure and its guards; do not expand scope into token persistence, shell mutation, or MCP onboarding.

## References

- Source files: `main.py:329-396`; `schemas.py:63-68`; `onboarding_cli.py:172-281`; `mcp_server.py:80-119`; `README.md:35-142`; `AGENTS.md:6-10`.
- Related plans: `context/changes/cli-onboarding-bootstrap/plan.md` (Phase 3); `context/archive/2026-08-06-developer-onboarding-token/plan.md` (Desired End State).
- Investigation tasks: token delivery trace; host secret-boundary assessment; independent prior-decision cross-check.
