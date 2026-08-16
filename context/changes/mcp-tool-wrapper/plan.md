# MCP Tool Wrapper Implementation Plan

## Overview

Implement S-03 as a standalone, locally launched stdio MCP server. The server will read a per-developer AzLimits API base URL and raw API token from its environment, forward the typed search inputs to the existing protected REST endpoint, and return the complete source-backed response without altering provenance or authorization behavior.

The MCP server is an adapter, not a second query or authorization implementation. All protected limitation data continues to flow through `GET /limitations/search`, where the existing FastAPI dependency enforces the token and active Demo license on every request.

## Current State Analysis

The completed REST query core already provides the required protected-data contract: `main.py` validates `q`, `region`, and `sku`; applies `require_active_license`; returns verified-only records; and serializes a `SearchResponse` whose records require provenance. `auth.py` rejects missing, malformed, unknown, expired, and orphaned Bearer tokens with `401`, then rejects users lacking an active Demo license with `403`.

Phase 1 added the MCP v2 dependency and independently testable REST forwarding boundary in `mcp_server.py`. What remains is MCP v2 server registration, the stdio entry point, a direct `anyio` development dependency, and in-memory adapter coverage. `httpx` and `respx` remain the outbound-client and isolated HTTP-test dependencies.

## Desired End State

A developer who has completed onboarding can configure a local MCP host with their own raw API token and API base URL, then invoke one MCP tool with `q` and optional `region` and `sku`. The tool forwards those values with `Authorization: Bearer <configured token>` to `/limitations/search` and returns the full typed search response, including the support-status verdict and provenance-complete records.

The tool never accepts a token argument, never persists or logs the configured token, and returns deterministic safe failures: a configuration failure for missing/invalid settings, an authentication failure for REST `401`, a license failure for REST `403`, and an upstream-unavailable failure for timeouts and REST `5xx` responses. Other REST contract failures are treated as an upstream failure without exposing the API response body or request headers.

### Key Discoveries:

- `main.py:441-486` — `GET /limitations/search` is the established and protected search boundary; it validates inputs, serves verified-only rows, and constructs `SearchResponse`.
- `auth.py:38-81` — the REST route’s dependency validates the Bearer token and active `demo` license for every protected response.
- `schemas.py:6-36` — `SearchResponse` and `LimitationRecord` already express the required verdict and provenance contract as Pydantic models.
- `logging_middleware.py:7-14` and `AGENTS.md:8-10` — tokens must never appear in logs, error responses, source control, or public result data.
- `pyproject.toml:6-24` and `uv.lock` — the project is synchronized to official `mcp==2.0.0`, whose v2 server API is `mcp.server.MCPServer`; it does not provide `FastMCP`.
- The same SDK supports the selected stdio transport through `MCPServer.run()` and the in-memory `Client(mcp)` adapter-test harness. Python 3.12 satisfies its runtime requirement.

## What We're NOT Doing

- No change to FastAPI routes, query logic, database schema, migrations, token hashing, OAuth, license enforcement, or the REST response schema.
- No direct database or `query.py` access from the MCP tool; it must not create a path around the REST authorization boundary.
- No MCP HTTP/SSE/Streamable HTTP deployment, remote hosted MCP service, or Railway service changes; this slice is a local stdio process.
- No interactive OAuth flow, token generation, token rotation, or token revocation inside the MCP server.
- No shared service credential: every locally configured MCP process uses the developer’s own API token.
- No token tool argument, token echoing, response-body pass-through for failures, request-header logging, or secret persistence.
- No region/SKU filtering behavior beyond the REST contract: the values remain optional inputs that are currently echoed but not applied as data filters.
- No response summarization that omits or rewrites backing records and provenance.

## Implementation Approach

Add a small `mcp_server.py` module with two separable concerns:

1. A configuration and REST-client boundary reads `AZLIMITS_API_BASE_URL` and `AZLIMITS_API_TOKEN`, validates the base URL and token presence, applies a 10-second connect/read timeout, disables redirect following, sends the token only as the authorization header, validates a successful payload as `SearchResponse`, and maps failures to dedicated exceptions whose messages start with a stable error code.
2. An official-MCP-v2 `MCPServer` registers one typed `search_limitations` tool. The tool exposes `q`, `region`, and `sku`, delegates only to the REST-client boundary, and returns the validated search response as structured MCP content. Client failures are re-raised as ordinary exceptions so the SDK returns `is_error=True`; do not raise `MCPError`.

Phase 1 tests call the client boundary directly with `respx`-mocked HTTP responses. Phase 2 adapter tests use the official in-memory `Client(mcp)` harness. Neither path needs a database, a running FastAPI server, live secrets, or a live MCP host. The README will give an explicit setup path that references the existing onboarding flow and commands the user to place their raw token only in an approved environment or host-secret configuration.

## Critical Implementation Details

The HTTP client is the authorization boundary from the MCP process: no tool code may construct data from `query.py`, the ORM, or raw response JSON. Successful API payloads must validate against the existing `SearchResponse` model before the MCP layer returns them, so missing provenance or an unexpected server response becomes a safe upstream contract failure instead of an incomplete public record.

Configuration and error paths must not include the token, the full `Authorization` header, a response body, a redirect `Location`, or an API URL query string in a raised tool error or log message. The error vocabulary is intentionally stable so callers can distinguish remedial actions without receiving lower-level server details.

Official MCP Python SDK v2 uses `MCPServer`, not `FastMCP`. Raise a dedicated exception whose message starts with the stable code plus a short remediation sentence (`azlimits_authentication_error: check the configured API token.`). `MCPServer` wraps that as an `is_error=True` tool result the model can read. Do not raise `MCPError`: that becomes a JSON-RPC failure the model never sees.

## Phase 1: Authorized REST Client Boundary

### Overview

Add the official MCP dependency and an independently testable configuration/client boundary that is the only code allowed to communicate with protected AzLimits data from the MCP process.

### Changes Required:

#### 1. MCP SDK dependency

**File**: `pyproject.toml`

**Intent**: Add the maintained official Python MCP SDK on its current v2 major line so the project can register typed MCP tools and run a stdio server.

**Contract**: Declare the `mcp` runtime dependency with a v2-compatible bound. Regenerate `uv.lock` through the normal `uv` workflow. Keep `httpx` as the outbound HTTP implementation and retain `respx` as the mock transport used by tests.

#### 2. Configuration, client, and error contract

**File**: `mcp_server.py` (new)

**Intent**: Define the safe configuration and authorized API-client layer before any MCP tool registration, so credential handling, response validation, timeouts, and error mapping are reviewable independently.

**Contract**:

- Require `AZLIMITS_API_BASE_URL` and `AZLIMITS_API_TOKEN` from the process environment. Reject an absent, blank, or malformed base URL and an absent or blank token as the stable `azlimits_configuration_error` without including either raw setting.
- Construct the search URL from the configured base URL and the fixed `/limitations/search` path; normalize a trailing base-URL slash so the result is exact`httpx.Timeout(10.0)` for both connect and read. Construct the client with `follow_redirects=False`. Do not put a token in URL parameters or request content.
- For `200`, parse the JSON into the existing `schemas.SearchResponse` before returning it. A malformed payload, unexpected non-success status, timeout, transport error, redirect (`3xx`), or `5xx` maps to `azlimits_upstream_unavailable` without forwarding API bodies, headers, or the `Location` value.
- Map REST `401` to `azlimits_authentication_error` and REST `403` to `azlimits_license_error`. Raise a dedicated exception whose message starts with that stable code, then a colon and a short remediation sentence only (check the configured token; check the Demo license). Nn in URL parameters or request content.
- For `200`, parse the JSON into the existing `schemas.SearchResponse` before returning it. A malformed payload, unexpected non-success status, timeout, transport error, or `5xx` maps to `azlimits_upstream_unavailable` without forwarding API bodies or headers.
- Map REST `401` to `azlimits_authentication_error` and REST `403` to `azlimits_license_error`. These errors state the corrective class only (check the configured token; check the Demo license) and never echo the token or server-supplied detail.
- Keep the module free of database, FastAPI, and logging dependencies. It must neither print nor log configuration, headers, request payloads, or response payloads.

#### 3. REST-client unit tests

**File**: `tests/test_mcp_server.py` (new)

**Intent**: Lock down the forwarding boundary with mocked HTTP so later MCP-adapter changes cannot bypass, leak, or distort the protected REST contract.

**Contract**: Use `respx` and environment isolation to prove all of the following without a live server or token:

- A valid invocation calls the configured `/limitations/search` URL exactly once, forwards `q`, `region`, and `sku`, and sends exactly the Bearer header derived from the configured token.
- The parsed result is a `SearchResponse` preserving the query context, verdict, count, and every record field including source URL, source title, quote, confidence, and verification state.
- Missing or blank configuration fails before making an HTTP request and does not include settings in the error.
- REST `401`, REST `403`, timeout/transport failure, redirect/`3xx`, `5xx`, and invalid success payloads each yield the selected stable safe failure class and do not include token/header/`Location`/response-body content.
- A client-side validation failure for out-of-contract input does not issue a request.

### Success Criteria:

#### Automated Verification:

- Focused MCP client tests pass: `uv run pytest tests/test_mcp_server.py -v`
- Full regression suite passes: `uv run pytest tests/ -v`
- Linting passes: `uv run ruff check .`
- Type checking passes: `uv run mypy mcp_server.py tests/test_mcp_server.py`

#### Manual Verification:

- Review the diff to confirm no token value, header, response body, or configuration dump is added to a logger, exception message, or test assertion output.
- Review the dependency lock update to confirm the selected official MCP SDK stays on its v2 major line.

**Implementation Note**: After completing this phase and all automated verification passes, pause for human confirmation that the credential boundary and dependency update meet expectations before proceeding.

---

## Phase 2: Stdio MCP Search Tool

### Overview

Register the single MCP tool through the official SDK and expose a runnable stdio entry point that delegates to the Phase 1 client boundary without changing its authorization or response semantics.

### Changes Required:

#### 1. Typed MCP server and tool registration

**File**: `mcp_server.py`

**Intent**: Turn the tested client boundary into the primary agent-facing surface: one MCP tool that accepts a limitation-search intent and returns the complete source-backed result.

**Contract**:

- Import `MCPServer` from `mcp.server`, create an official-MCP-v2 server named for AzLimits, and register exactly one `search_limitations` tool. Do not import or reference `FastMCP`.
- The tool signature exposes required `q` plus optional `region` and `sku`; it does not expose API URLs, tokens, authorization headers, or database-oriented inputs.
- The tool description tells agents that it returns known, verified Azure limitation records and a support-status verdict with source evidence. It does not claim that an empty result proves the absence of a limitation.
- Delegate the complete invocation to the Phase 1 boundary. On success, return the validated `SearchResponse` as structured MCP content unchanged; do not produce a prose-only summary or drop records/provenance.
- Re-raise the Phase 1 dedicated exceptions unchanged so the official SDK returns `is_error=True` with the exception message in `content`. Do not catch them and `return` an error string, and do not raise `MCPError`. The message already starts with the stable code plus concise remediation; the adapter must not append API status bodies, headers, token values, or untrusted response text.
- Provide the MCP-v2-supported executable entry point (`if __name__ == "__main__": mcp.run()`) for the default stdio transport. Running it must not require FastAPI settings, database settings, OAuth credentials, or a database connection.

#### 2. MCP adapter tests

**File**: `tests/test_mcp_server.py`

**Intent**: Prove the registered tool exposes the agreed consumer contract and does not replace the validated REST-client behavior with an alternate code path.

**Contract**: Add `anyio` as a direct development dependency and regenerate `uv.lock`. Use the official MCP-v2 in-memory harness `async with Client(mcp)` where `mcp` is the registered `MCPServer`, plus `@pytest.mark.anyio`, with the Phase 1 `respx` HTTP mock in place. Do not add a second async runner. Assert:

- The tool schema requires `q`, permits omitted `region`/`sku`, and does not declare a credential parameter.
- A successful tool call returns `structured_content` equivalent to the complete `SearchResponse`, including all record provenance fields and the support-status verdict.
- Omitted optional filters are forwarded as omitted REST query parameters rather than stringified null-like values.
- Each selected client failure returns `is_error=True` with the stable code at the start of `content` text and has no secret-bearing text.
- No test starts a web server, invokes FastAPI, accesses Postgres, or requires a real MCP host process.

### Success Criteria:

#### Automated Verification:

- MCP client and adapter tests pass: `uv run pytest tests/test_mcp_server.py -v`
- Full regression suite passes: `uv run pytest tests/ -v`
- Linting passes: `uv run ruff check .`
- Type checking passes: `uv run mypy mcp_server.py tests/test_mcp_server.py`

#### Manual Verification:

- Start the stdio server with a test or disposable token configured through the MCP host/environment, inspect the discovered `search_limitations` schema, and confirm credentials are absent from its inputs.
- Invoke `search_limitations` for `AKS` and confirm the displayed structured result includes the support verdict plus source URL, quote, confidence, and verification state for every record.
- Remove or expire the configured token, invoke the tool again, and confirm an authentication-class failure appears without revealing the token or an API response body.

**Implementation Note**: After completing this phase and all automated verification passes, pause for human confirmation that the MCP host behavior is usable and safe before proceeding.

---

## Phase 3: Operator Setup and Slice Reconciliation

### Overview

Document the local MCP-host setup and reconcile S-03 planning status so users can configure the supported workflow without accidentally treating the raw API token as an ordinary tool parameter or source-controlled setting.

### Changes Required:

#### 1. MCP setup documentation

**File**: `README.md`

**Intent**: Add a concise MCP-specific setup section that connects the existing onboarding/token lifecycle to the new local stdio server.

**Contract**:

- State that users must first complete the documented onboarding flow and save the one-time raw API token in an approved secret store.
- Document `AZLIMITS_API_BASE_URL` and `AZLIMITS_API_TOKEN` as the only MCP-process settings, including a local example that avoids hard-coding a real secret. Do not add token values to sample MCP tool calls.
- State the stdio command/host registration form that launches the server through `uv`, and identify `search_limitations(q, region?, sku?)` as the supported tool.
- Explain the stable failure classes and their safe corrective action: configuration, authentication, Demo license, and upstream availability.
- Restate that the server is a local stdio process and that its API token must not be passed as a tool argument, committed, printed, or placed in shell history/logs.

#### 2. Roadmap status reconciliation

**File**: `context/foundation/roadmap.md`

**Intent**: Reflect that S-03 has a reviewed implementation plan while preserving `done` strictly for delivered functionality.

**Contract**: Update the S-03 status and backlog handoff consistently to point readers at `context/changes/mcp-tool-wrapper/` as the active planned slice. Do not mark S-03 complete until implementation, verification, and review have landed.

### Success Criteria:

#### Automated Verification:

- Documentation references the implemented module, environment variable names, tool name, and test command correctly.
- All MCP tests pass after documentation and roadmap edits: `uv run pytest tests/test_mcp_server.py -v`
- Full regression suite passes: `uv run pytest tests/ -v`
- Linting passes: `uv run ruff check .`
- Type checking passes: `uv run mypy .`

#### Manual Verification:

- Follow the README from a clean MCP-host configuration using a test token and confirm the tool is discoverable and callable without `DATABASE_URL`, OAuth credentials, or a running FastAPI process.
- Confirm all secret examples remain placeholders and that no documentation advises users to enter a token into a tool call or commit it to a configuration file.
- Confirm roadmap S-03 wording matches the delivered stdio-wrapper scope and does not suggest remote deployment or direct query-core access.

**Implementation Note**: After completing this phase and all automated verification passes, pause for human confirmation that the setup guide is accurate before considering the slice ready for implementation review.

---

## Testing Strategy

### Unit Tests:

- Environment configuration: missing, blank, malformed, and valid base URL/token values.
- Input validation for required and bounded `q`, `region`, and `sku` before an outbound request begins.
- REST status, redirect, and transport-error mapping to dedicated exceptions whose messages start with the stable safe error vocabulary.
- Successful Pydantic validation of the existing `SearchResponse`; reject an incomplete or malformed API payload.
- MCP tool schema: intended search parameters only, with no credentials or transport configuration exposed.

### Integration Tests:

- `respx` mocks confirm an authorized `GET /limitations/search` uses the configured base URL, exact query mapping, `httpx.Timeout(10.0)`, `follow_redirects=False`, and Bearer forwarding.
- A successful in-memory `Client(mcp)` invocation returns the complete structured REST contract, including every provenance field.
- `401`, `403`, timeout/transport failures, redirects, `5xx`, and malformed payloads become `is_error=True` MCP results whose `content` starts with the stable code and contains no secret or server-body leakage.

### Manual Testing Steps:

1. Obtain a disposable or developer-owned API token through the existing onboarding flow and store it in the MCP host’s approved secret configuration.
2. Configure `AZLIMITS_API_BASE_URL` for a running AzLimits API and `AZLIMITS_API_TOKEN` without placing the raw value in source control or a tool argument.
3. Register and start the stdio MCP server through the documented `uv` command, then inspect the discovered tool schema.
4. Call `search_limitations` with `q="AKS"`, and confirm the structured response includes `support_status`, `record_count`, and each record’s `source_url`, `source_title`, `quote`, `confidence`, and `verification_state`.
5. Call the tool with `region` and `sku`, and confirm they appear in the returned query context while retaining the REST v1 note that they are not filters.
6. Temporarily use an expired/invalid token and verify the authentication failure class contains no token, header, API body, or request details.
7. Remove a required configuration value and verify the configuration failure occurs without an outbound request or secret disclosure.

## Performance Considerations

The MCP wrapper adds one local serialization step and one outbound REST round-trip. Use `httpx.Timeout(10.0)` so a non-responsive API cannot block an agent indefinitely. It must not add retries in this slice: automatically replaying a request with a long-lived bearer token can amplify latency and complicate failure semantics without helping the current low-QPS MVP. Do not follow redirects; a `3xx` is an upstream failure, not a second authorized hop.

The response can contain up to the REST endpoint’s existing 500-record limit. The MCP server returns this response unchanged by product decision; pagination, truncation, ranking, caching, and summary generation are out of scope.

## Migration Notes

No database or data migration is required. The only remaining dependency migration is the normal `uv` lockfile update after adding direct `anyio` support for the Phase 2 pytest plugin. The already-locked official MCP SDK remains on its v2 major line. Existing API consumers and the FastAPI application remain unchanged.

## References

- Frame: `context/changes/mcp-tool-wrapper/frame.md`
- Research: `context/changes/mcp-tool-wrapper/research.md`
- Product requirements: `context/foundation/prd.md` — US-01, FR-007, FR-010, FR-012
- Roadmap slice: `context/foundation/roadmap.md` — S-03
- REST query boundary: `main.py:441-486`
- Token and license gate: `auth.py:38-81`
- Existing response contract: `schemas.py:6-36`
- Secret logging rule: `logging_middleware.py:7-14`, `AGENTS.md:8-10`
- Test risk map: `context/foundation/test-plan.md` — Risks #1, #2, #3, #4, #6
- Official SDK: `https://github.com/modelcontextprotocol/python-sdk`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Authorized REST Client Boundary

#### Automated

- [x] 1.1 Focused MCP client tests pass: `uv run pytest tests/test_mcp_server.py -v` — 12ffc9e
- [x] 1.2 Full regression suite passes: `uv run pytest tests/ -v` — 12ffc9e
- [x] 1.3 Linting passes: `uv run ruff check .` — 12ffc9e
- [x] 1.4 Type checking passes: `uv run mypy mcp_server.py tests/test_mcp_server.py` — 12ffc9e

#### Manual

- [x] 1.5 Review confirms no token or secret-bearing HTTP data is logged or exposed by the new boundary — 12ffc9e
- [x] 1.6 Review confirms the lockfile uses the official MCP SDK on the selected v2 major line — 12ffc9e

### Phase 2: Stdio MCP Search Tool

#### Automated

- [x] 2.1 MCP client and adapter tests pass: `uv run pytest tests/test_mcp_server.py -v`
- [x] 2.2 Full regression suite passes: `uv run pytest tests/ -v`
- [x] 2.3 Linting passes: `uv run ruff check .`
- [x] 2.4 Type checking passes: `uv run mypy mcp_server.py tests/test_mcp_server.py`

#### Manual

- [x] 2.5 Stdio server exposes a credential-free `search_limitations` schema
- [x] 2.6 `search_limitations(q="AKS")` returns verdict and complete source-backed records
- [x] 2.7 Invalid or expired token returns a non-secret authentication-class MCP failure

### Phase 3: Operator Setup and Slice Reconciliation

#### Automated

- [ ] 3.1 Documentation references the implemented module, variables, tool, and test command correctly
- [ ] 3.2 MCP tests pass after documentation and roadmap edits: `uv run pytest tests/test_mcp_server.py -v`
- [ ] 3.3 Full regression suite passes: `uv run pytest tests/ -v`
- [ ] 3.4 Linting passes: `uv run ruff check .`
- [ ] 3.5 Type checking passes: `uv run mypy .`

#### Manual

- [ ] 3.6 Clean MCP-host setup works without database or OAuth application settings
- [ ] 3.7 Documentation contains only placeholders and never presents a token as a tool argument or committed value
- [ ] 3.8 Roadmap S-03 wording matches the local stdio-wrapper scope
