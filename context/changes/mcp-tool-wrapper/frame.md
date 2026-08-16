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