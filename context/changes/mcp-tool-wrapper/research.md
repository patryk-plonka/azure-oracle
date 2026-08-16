---
date: 2026-08-16T14:21:52Z
researcher: GitHub Copilot
git_commit: 8c40f3cd3d6f26e6c8a3bd01d692398942fd14db
branch: main
repository: patryk-plonka/azure-oracle
topic: "verify if mcp will have everything to use Bearer token to communicate with api"
tags: [research, codebase, mcp, authentication, bearer-token]
status: complete
last_updated: 2026-08-16
last_updated_by: GitHub Copilot
---

# Research: MCP Bearer-token API readiness

**Date**: 2026-08-16T14:21:52Z
**Researcher**: GitHub Copilot
**Git Commit**: 8c40f3cd3d6f26e6c8a3bd01d692398942fd14db
**Branch**: main
**Repository**: patryk-plonka/azure-oracle

## Research Question

verify if mcp will have everything to use Bearer token to communicate with api

## Summary

**The REST API is ready to accept a Bearer token from an MCP process. The MCP process is not yet implemented, so it currently has no token configuration, HTTP client, tool registration, or error mapping.**

A completed onboarding flow produces a 90-day raw API token exactly once. The protected search endpoint accepts that value as `Authorization: Bearer <token>`, validates the hashed token and expiry, then requires an active `demo` license. This gives the future MCP wrapper a complete server-side authentication contract.

S-03 still needs to decide and implement how its MCP host receives and retains the raw token, its API base URL, and how it forwards the header on every REST request. It must not call the query implementation directly unless it invokes the same token and license enforcement boundary; a direct call would bypass the protection required by the product guardrails.

## Detailed Findings

### API-side Bearer-token contract is complete

- [`get_current_user`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/auth.py#L38-L62) requires an `Authorization` header with the `Bearer ` prefix, hashes the supplied raw token, looks up the hash, and rejects missing, malformed, unknown, expired, or orphaned credentials with `401`.
- [`require_active_license`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/auth.py#L65-L81) composes the token check with an active `demo`-license lookup. A valid token without that license is rejected with `403`.
- [`GET /limitations/search`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/main.py#L441-L486) is the intended REST boundary for the future tool. It accepts `q` plus optional `region` and `sku`, and applies `require_active_license` before querying verified records.
- The response maps every result to source URL, source title, quote, confidence, and verification metadata at the endpoint boundary. Passing the request through this route preserves the source-provenance guardrail.

The future MCP client request is therefore mechanically straightforward:

```http
GET /limitations/search?q=AKS HTTP/1.1
Host: <api-base-url>
Authorization: Bearer <raw-api-token>
```

### API-token lifecycle supports MCP use

- [`POST /auth/tokens`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/main.py#L347-L407) consumes a short-lived issuance credential, rechecks the active Demo license, creates a token valid for 90 days, persists only its hash, and returns the raw token in the creation response.
- The token has an opaque ID and can be expired by its owner through [`POST /auth/tokens/{token_id}/expire`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/main.py#L419-L434). The wrapper should surface the resulting `401` on later search calls as an actionable authentication failure.
- Tests cover the API boundary's missing, malformed, invalid, expired, Demo, and non-Demo cases in [`tests/test_auth_dependencies.py`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/tests/test_auth_dependencies.py) and [`tests/test_limitations_search.py`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/tests/test_limitations_search.py).
- [`logging_middleware.py`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/logging_middleware.py#L1-L91) redacts the Authorization header. The MCP wrapper must uphold the same property by never logging its token, request headers, or raw configuration value.

### MCP wrapper has no current implementation

- S-03 is still marked `proposed` in the roadmap and is explicitly described as an MCP wrapper over the established query core: [`context/foundation/roadmap.md`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/context/foundation/roadmap.md#L56-L57) and [`context/foundation/roadmap.md`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/context/foundation/roadmap.md#L177-L190).
- The repository has no MCP SDK dependency, MCP server module, tool definition, token configuration, or MCP tests. Its dependencies do include `httpx`, which is sufficient for an HTTP forwarding client once an MCP SDK is selected: [`pyproject.toml`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/pyproject.toml#L6-L21).
- The current `mcp-tool-wrapper` folder contains only its change identity file. It does not change application behavior yet.

### Minimum MCP-side contract to implement

For an MCP host that communicates with this REST API, the plan needs these explicit decisions and deliverables:

1. **Secret inputs**: require an API base URL and raw API token from MCP-host configuration, preferably environment variables or the host's secret store. Do not add them to tool arguments, source control, logs, response text, or process invocation history. Their exact names remain a planning decision.
2. **One HTTP client boundary**: construct a client with a bounded timeout and send `Authorization: Bearer <token>` for every protected call. `httpx` is already an application dependency.
3. **A tool input contract**: expose `q`, `region`, and `sku` with the REST endpoint's bounds. Do not expose a token parameter to callers.
4. **Response mapping**: deserialize the documented search response and return all provenance fields unchanged, including source URL, quote, confidence, and verification state.
5. **Failure mapping**: identify `401` as invalid, expired, or missing configured token; identify `403` as inactive/non-Demo license; treat timeouts and `5xx` responses as upstream availability failures. Do not include response request headers or secret-bearing details in tool errors.
6. **Regression coverage**: mock the REST client and prove that the header is sent, all tool inputs map to query parameters, provenance survives mapping, and `401`, `403`, timeout, and server-error behavior is deterministic.

### HTTP forwarding versus direct query reuse

The query-core work intended reuse by S-03, but that does not by itself authorize bypassing REST authentication. The archived S-01 plan says the query core should be reused unchanged by the MCP wrapper: [`context/archive/2026-08-03-rest-search-query-core/plan.md`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/context/archive/2026-08-03-rest-search-query-core/plan.md#L143). For this research question, the safe interpretation is an HTTP wrapper around `/limitations/search`, because that path demonstrably enforces the Bearer token and Demo license on every request.

If planning instead embeds the MCP tool in the FastAPI process and calls shared query functions directly, it must explicitly invoke equivalent token and license checks first. Otherwise it violates the product rule that protected data is never returned without both a valid token and an active Demo license.

## Code References

- [`auth.py`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/auth.py#L38-L81) - Bearer parsing, token hash lookup, expiry validation, and Demo-license dependency.
- [`main.py`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/main.py#L347-L486) - API-token issuance, owner expiration, auth probe, and protected search endpoint.
- [`schemas.py`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/schemas.py#L1-L101) - Search and onboarding response contracts.
- [`pyproject.toml`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/pyproject.toml#L6-L21) - Existing HTTP client dependency and absence of an MCP SDK.
- [`context/foundation/prd.md`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/context/foundation/prd.md#L42-L58) - MCP product intent and protected-data guardrails.

## Architecture Insights

The current design separates long-lived API access from onboarding handoffs. OAuth and EULA/issuance credentials are short-lived, single-use state; the raw API token is the only credential suitable for a persistent MCP host configuration. The database stores only its hash, so the host operator must retain the raw value when it is returned at creation time.

Routing MCP requests through the REST API creates one enforcement point for token validity, entitlement, verified-only data, provenance, and request logging. This is the smallest design that demonstrates the required Bearer-token communication and prevents the two client surfaces from drifting.

## Historical Context (from prior changes)

- [`context/archive/2026-08-06-developer-onboarding-token/plan.md`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/context/archive/2026-08-06-developer-onboarding-token/plan.md#L63-L83) defined the onboarding flow that creates the hash-only, 90-day API token after explicit EULA acceptance and active Demo license assignment.
- [`context/archive/2026-08-03-rest-search-query-core/plan.md`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/context/archive/2026-08-03-rest-search-query-core/plan.md#L48-L56) defined the protected REST contract that S-03 should preserve.
- [`context/foundation/roadmap.md`](https://github.com/patryk-plonka/azure-oracle/blob/8c40f3cd3d6f26e6c8a3bd01d692398942fd14db/context/foundation/roadmap.md#L177-L190) positions S-03 after S-01 and describes it as returning the same source-backed records and support-status verdict.

## Related Research

No prior `research.md` artifact specifically addresses the MCP wrapper. The archived onboarding and REST-query plans above are the relevant historical evidence.

## Open Questions

1. Which MCP Python SDK and transport should the wrapper use?
2. Should the tool be a separate MCP process that calls the REST API over HTTP, or be hosted by the existing FastAPI process? The HTTP client approach is recommended because it preserves the existing authorization boundary without duplication.
3. Which secret-configuration mechanism and variable names should provide the base URL and raw API token to the MCP host?
4. Is one service-level Demo token acceptable for the initial MCP deployment, or does the product require a separate MCP host per developer token?
5. What tool-error shape should callers receive for `401`, `403`, timeout, and `5xx` API failures?
