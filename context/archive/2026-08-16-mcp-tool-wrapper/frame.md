# Frame Brief: MCP Bearer-token API integration

> Framing step before /10x-plan. This document captures what is *actually*
> at issue, separated from what was initially assumed.

## Reported Observation

The future MCP surface has no token-forwarding behavior yet and must
communicate with the protected API using a Bearer token.

## Initial Framing (preserved)

- **User's stated cause or approach**: The API or token lifecycle may not provide everything an MCP client needs to use a Bearer token.
- **User's proposed direction**: Verify readiness, then add an MCP tool wrapper that uses the established Bearer-token contract.
- **Pre-dispatch narrowing**: MCP has no token-forwarding behavior yet.

## Dimension Map

The observation could originate at any of these dimensions:

1. **REST authentication and entitlement boundary** - the API might not accept, validate, or authorize Bearer-token requests from an external client.  <- initial framing
2. **MCP host integration surface** - the repository might lack an MCP server, tool registration, secret configuration, and client behavior needed to make a request.
3. **Protected-data boundary preservation** - an eventual wrapper might avoid the token/license or provenance rules enforced by the REST route.

## Hypothesis Investigation

| Hypothesis | Evidence | Verdict |
| --- | --- | --- |
| REST authentication or token lifecycle is not MCP-ready | `auth.py:38-81` validates Bearer tokens and the Demo license; `main.py:347-407` issues a 90-day raw token once; `main.py:441-490` applies the gate to search; `tests/test_limitations_search.py:1-50` covers the gate. | NONE as the source of the observation |
| MCP host integration is absent | `pyproject.toml:6-21` has no MCP SDK; no MCP module, registration, configuration, forwarding client, or tests exist; `context/foundation/roadmap.md:56` lists S-03 as proposed. | STRONG |
| A wrapper could drift around the protected-data boundary | `main.py:441-490` and `schemas.py:5-20` enforce authorization and provenance at the REST route; `context/changes/mcp-tool-wrapper/research.md:76-79` identifies bypass as a risk if an alternative integration does not reapply these rules. | WEAK as a current cause; STRONG as a planning constraint |

## Narrowing Signals

- The selected leading concern was: "MCP has no token-forwarding behavior yet."
- All investigators found the API accepts and enforces Bearer-token access, while the repository contains no MCP process or token-forwarding behavior.
- The independent investigation found S-03 deliberately follows the completed REST query core, rather than documenting an incomplete authentication feature.

## Cross-System Convention

Protected limitation data is exposed through a single boundary that checks a valid token and active Demo license before returning source-backed records. This convention is stated in `AGENTS.md:8-10`, implemented in `auth.py:38-81` and `main.py:441-490`, and validated by the search tests. The leading hypothesis matches the roadmap convention that MCP follows the validated REST query core (`context/foundation/roadmap.md:43-44`, `context/foundation/roadmap.md:56`).

## Reframed (or Confirmed) Problem Statement

> **The actual problem to plan around is**: the API-side Bearer-token contract is ready, but the planned MCP surface has not been implemented to obtain a configured token, make protected requests, and preserve the existing authorization and provenance contract.

The initial concern about API readiness does not hold: the API already authenticates, authorizes, and returns provenance-complete search results. The remaining work is the deliberately sequenced MCP integration surface, with the existing protected-data boundary as a non-negotiable constraint. No MCP architecture is selected by this framing step.

## Confidence

- **HIGH** - strong code and test evidence confirms the API contract, the repository has no MCP implementation, and the roadmap independently identifies this as the next planned slice.

## What Changes for /10x-plan

The plan should focus on the missing MCP integration contract and its observable behavior, rather than redesigning API-token validation. It must retain the established token, Demo-license, and provenance guarantees regardless of the eventual hosting or transport decision.

## References

- Source files: `auth.py:38-81`; `main.py:347-407`; `main.py:441-490`; `schemas.py:5-20`; `pyproject.toml:6-21`; `tests/test_limitations_search.py:1-50`
- Related research: `context/changes/mcp-tool-wrapper/research.md`
- Investigation tasks: read-only Explore investigations for API auth boundary, MCP configuration gap, boundary preservation, and independent issue identification

---

# Frame Brief: MCP Tool Wrapper Phase 2 SDK Mismatch

> Framing step during implementation. This document records the observed
> dependency/API mismatch separately from its initially assumed cause.

## Reported Observation

`uv run` cannot import `mcp.server.fastmcp` although the project declares
`mcp>=2,<3`; `anyio` is also absent as a direct development dependency.

## Initial Framing (preserved)

- **User's stated cause or approach**: Phase 1's dependency or lockfile state may be incomplete or inconsistent with Phase 2.
- **User's proposed direction**: Frame the mismatch before deciding whether implementation should adapt, skip, or be re-planned.
- **Pre-dispatch narrowing**: The leading concern is plan accuracy: its selected SDK API may not match the declared `mcp>=2,<3` package.

## Dimension Map

The observation could originate at any of these dimensions:

1. **Dependency resolution and environment selection** — the active environment could differ from the resolved lockfile.
2. **SDK package layout/API** — the selected v2 package could expose server registration at a different module path.  ← initial framing
3. **Plan dependency specification** — the selected range could omit the dependency version or API verification Phase 2 requires.
4. **Phase 2 test-harness assumption** — the documented in-memory client harness could be absent from the selected SDK.

## Hypothesis Investigation

| Hypothesis | Evidence | Verdict |
| --- | --- | --- |
| Environment drift explains the import failure | `pyproject.toml` declares `mcp>=2,<3`; `uv.lock` and `.venv` both resolve/install `mcp==2.0.0`. | NONE |
| The v2 SDK uses a different server API | Installed `mcp.server` exports `MCPServer`; its package contains no `fastmcp` module or `FastMCP` symbol. | STRONG |
| The manifest misses a Phase 2 direct test dependency | `plan.md` Phase 2 requires direct `anyio`; `pyproject.toml` includes it only transitively through `mcp`. | STRONG |
| `Client(mcp)` is unsupported in v2 | Installed `mcp.client.Client` documents in-process `MCPServer` support, including `async with Client(mcp)`. | NONE |

## Narrowing Signals

- The active environment exactly matches the lockfile, so synchronization cannot make `mcp.server.fastmcp` available.
- The selected `mcp==2.0.0` retains the planned in-memory test style but names its server class `MCPServer`.
- Phase 2's direct-`anyio` requirement has not yet been carried into the development dependency group.

## Cross-System Convention

This repository uses `uv` and `uv.lock` as the dependency source of truth.
The lockfile and environment agree, so implementation must target the
official API actually selected by the approved v2 dependency rather than an
API path associated with another major-version layout.

## Reframed (or Confirmed) Problem Statement

> **The actual problem to plan around is**: Phase 2 contains an SDK API assumption incompatible with the already selected and synchronized official MCP v2 package, plus an unfulfilled direct `anyio` test dependency requirement.

The initial suspicion of an incomplete dependency installation does not hold.
The implementation can retain `mcp>=2,<3` and the in-memory client-test
approach, but must use v2's `MCPServer` API and declare `anyio` directly before
claiming the Phase 2 contract is satisfied.

## Confidence

- **HIGH** — the lockfile, installed package metadata, package exports, and in-memory client implementation all agree.

## What Changes for /10x-plan

The existing plan's stdio-server intent remains valid, but its Phase 2
implementation must target `from mcp.server import MCPServer` rather than
`FastMCP`; the direct development dependency requirement for `anyio` must also
be reconciled. No REST client or authorization design change is needed.

## References

- Source files: `pyproject.toml:6-24`; `uv.lock` `mcp` package record; `mcp_server.py:1-129`; `context/changes/mcp-tool-wrapper/plan.md` Phase 2.
- Installed SDK: `.venv/Lib/site-packages/mcp/server/__init__.py`; `.venv/Lib/site-packages/mcp/client/client.py`.
- Related research: `context/changes/mcp-tool-wrapper/research.md`.
- Investigation tasks: installed SDK layout, plan-assumption comparison, lockfile/environment-alignment exploration.