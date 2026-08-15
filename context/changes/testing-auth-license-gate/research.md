---
date: 2026-07-26T14:20:35+02:00
researcher: GitHub Copilot
git_commit: d0835c9213d74803471759d279477546fb69357d
branch: main
repository: patryk-plonka/azure-oracle
topic: "Risk #3: token and Demo-license access control"
tags: [research, codebase, authentication, licensing, fastapi, testing]
status: complete
last_updated: 2026-07-26
last_updated_by: GitHub Copilot
---

# Research: Risk #3 Token and Demo-License Access Control

**Date**: 2026-07-26T14:20:35+02:00
**Researcher**: GitHub Copilot
**Git Commit**: d0835c9213d74803471759d279477546fb69357d
**Branch**: main
**Repository**: patryk-plonka/azure-oracle

## Research Question

For Test Plan Risk #3, identify the token and Demo-license validation entry
point, determine whether validation is per request or cached, and establish the
test oracle for missing or expired tokens and inactive licenses.

## Summary

There is no live token, OAuth, license, protected-route, or cache code yet.
The current FastAPI service exposes only an unauthenticated `/health` endpoint
behind trusted-host middleware. The future owner is foundation F-03,
`auth-scaffold-token-license`; the protected REST search surface arrives in
S-01.

The fixed product contract is that every protected response checks both an
unexpired token and active Demo license before any limitation data is reached.
The license check must happen on every request because its state can change
during a token's lifetime. The implementation and tests must not infer that a
valid token implies an active license.

## Detailed Findings

### Current Runtime Surface

- [`main.py`](https://github.com/patryk-plonka/azure-oracle/blob/d0835c9213d74803471759d279477546fb69357d/main.py#L1-L18)
  imports only FastAPI and `TrustedHostMiddleware`, configures allowed hosts,
  and exposes `/health`; it contains no `Depends`, authentication dependency,
  token parser, database access, or license check.
- [`tests/test_health.py`](https://github.com/patryk-plonka/azure-oracle/blob/d0835c9213d74803471759d279477546fb69357d/tests/test_health.py#L1-L10)
  exercises only the public health response. It cannot provide evidence about
  protected access.
- Therefore the research does not identify an existing validation entry point
  or cache to test. F-03 must create that entry point before Risk #3 can be
  implemented.

### Fixed Access-Control Contract

- The PRD guardrail requires a valid, unexpired token **and** active Demo
  license before protected data is returned:
  [`prd.md`](https://github.com/patryk-plonka/azure-oracle/blob/d0835c9213d74803471759d279477546fb69357d/context/foundation/prd.md#L63-L68).
- US-01 requires rejection when the token is missing or expired, or the
  license is inactive:
  [`prd.md`](https://github.com/patryk-plonka/azure-oracle/blob/d0835c9213d74803471759d279477546fb69357d/context/foundation/prd.md#L75-L91).
- FR-006 resolves the design question explicitly: token validity and Demo
  license state are validated before **every** protected response because a
  license can expire or be revoked mid-token-life:
  [`prd.md`](https://github.com/patryk-plonka/azure-oracle/blob/d0835c9213d74803471759d279477546fb69357d/context/foundation/prd.md#L109-L128).
- The access-control section repeats that an unauthenticated or unlicensed
  request is rejected before reaching limitation data and that tokens are
  stored as hashes with expiry and revocation support:
  [`prd.md`](https://github.com/patryk-plonka/azure-oracle/blob/d0835c9213d74803471759d279477546fb69357d/context/foundation/prd.md#L214-L230).

### Ownership and Sequencing

- F-03 owns GitHub OAuth, EULA acceptance, Demo-license assignment, hash-only
  token issuance, and per-request token-plus-license middleware:
  [`roadmap.md`](https://github.com/patryk-plonka/azure-oracle/blob/d0835c9213d74803471759d279477546fb69357d/context/foundation/roadmap.md#L103-L117).
- The protected REST query route is S-01, which depends on F-03 as well as the
  data and logging foundations:
  [`roadmap.md`](https://github.com/patryk-plonka/azure-oracle/blob/d0835c9213d74803471759d279477546fb69357d/context/foundation/roadmap.md#L135-L146).
- Secret stripping is separately owned by F-04. It shares Test Plan Phase 2
  because it protects the same access boundary, but is not required to define
  Risk #3's access oracle:
  [`roadmap.md`](https://github.com/patryk-plonka/azure-oracle/blob/d0835c9213d74803471759d279477546fb69357d/context/foundation/roadmap.md#L119-L131).

### Test Oracle for Risk #3

The Phase 2 integration contract, derived from the PRD rather than a future
implementation, is:

| Scenario | Required observable outcome |
|---|---|
| No token | Protected request is rejected before it obtains limitation data. |
| Expired token | Protected request is rejected before it obtains limitation data. |
| Active token, inactive Demo license | Protected request is rejected before it obtains limitation data. |
| Active token, active Demo license | Protected request can reach the protected handler and return its normal response. |
| License changes after a previous successful request | A subsequent request is rejected; prior success must not cache authorization. |

The final scenario is the discriminating regression test for the per-request
requirement. It should mutate the fixture's license state between two requests
using the same still-valid token, then assert the second request is rejected.
This is more valuable than an isolated inactive-license test because it fails
if an implementation caches the earlier successful authorization result.

The test plan already mandates this contract and calls out the happy-path-only
anti-pattern:
[`test-plan.md`](https://github.com/patryk-plonka/azure-oracle/blob/d0835c9213d74803471759d279477546fb69357d/context/foundation/test-plan.md#L74-L80).

## Architecture Insights

- Use a single FastAPI dependency or equivalent request boundary for the
  combined token and license decision, attached to every protected REST route
  and reused by the MCP adapter. This keeps the "reject before data" rule at
  the boundary instead of relying on individual query handlers.
- Separate authentication from authorization in the test fixtures: a valid
  token fixture must be able to pair with an inactive license fixture.
- Hash-only token storage means tests should seed or construct a known raw
  token and its corresponding stored hash; they must never expect a plaintext
  database token.
- Do not cache license authorization across requests. Request-local lookup is
  compatible with the contract; cross-request caching is not unless it
  revalidates mutable license state on every request.

## Historical Context

- The deployment scaffold deliberately contains no authentication surface;
  its completed change is limited to the health endpoint and host allow-list:
  [`context/changes/deploy-skeleton-health/change.md`](https://github.com/patryk-plonka/azure-oracle/blob/d0835c9213d74803471759d279477546fb69357d/context/changes/deploy-skeleton-health/change.md#L1-L16).
- Deployment configuration reserves `GITHUB_OAUTH_CLIENT_ID`,
  `GITHUB_OAUTH_CLIENT_SECRET`, `TOKEN_HASH_SALT`, and `DATABASE_URL` as
  Railway secrets. They must never be committed or returned in logs/errors:
  [`context/deployment/deploy-plan.md`](https://github.com/patryk-plonka/azure-oracle/blob/d0835c9213d74803471759d279477546fb69357d/context/deployment/deploy-plan.md#L42-L58).
- No prior research artifact exists for this change; Phase 1's import research
  is adjacent but does not decide authentication or license behavior.

## Related Research

- No related `research.md` artifact exists at the time of this research.

## Open Questions

- The PRD requires rejection but does not select HTTP status codes for missing,
  expired, and inactive-license states. Resolve these before asserting exact
  response codes in Phase 2 tests.
- F-02 has not defined the user, token, and license schema yet. The F-03 plan
  must choose how token expiry and mutable Demo-license state are persisted and
  how test fixtures safely update that state between requests.
- The protected route is not implemented. Phase 2 can first test the F-03
  boundary with a minimal protected probe route, then add coverage to S-01 once
  the query surface exists.