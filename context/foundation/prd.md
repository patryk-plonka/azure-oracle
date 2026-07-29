---
project: "AzLimits"
version: 1
status: draft
created: 2026-07-19
context_type: greenfield
product_type: api
target_scale:
  users: small
  qps: low
  data_volume: small
timeline_budget:
  mvp_weeks: 3
  hard_deadline: null
  after_hours_only: true
---

# PRD — AzLimits (Azure Oracle)

## Vision & Problem Statement

Azure design and IaC decisions are committed up front — teams know their target
services, regions, tools, languages, and deployment model at project start — but
the limitations that invalidate those choices (quotas, hard limits, unsupported
scenarios, known issues, preview caveats, deprecations, and regional / SKU /
networking / identity / tooling constraints) are discovered late, during
implementation, deployment, or release hardening. The cost is redesign, deployment
failures, release delays, unexpected quota requests, added spend, and unsupported
architecture decisions.

The insight: this information already exists, but it is trapped and scattered
across Microsoft docs, quota/limit pages, troubleshooting articles, GitHub
repositories, and public issue trackers. No single, structured, source-backed
dataset lets a consumer ask "is X supported in region Y with SKU Z?" before
committing. Because the decisions are made before anyone reads the scattered
sources, the check has to be delivered inline — to an AI agent at the moment it
generates or reviews IaC.

## User & Persona

**Primary persona — the IaC-generating AI agent (human in the loop).** An AI
coding agent or MCP-compatible client that generates or reviews Azure
infrastructure-as-code on behalf of a developer. The agent reaches for AzLimits
before emitting or approving IaC, queries relevant limitations with source
provenance, and uses the results to warn the user or adjust its recommendations.
A human developer configures the agent's AzLimits token and acts on the warnings.

### Secondary persona

Developers, platform engineers, architects, and DevOps teams querying the REST
API / CLI directly (Postman, scripts, PR review) during architecture design and
release planning. The MVP serves the agent path first; the human API path shares
the same data and endpoints.

## Success Criteria

### Primary
- An authenticated, Demo-licensed agent queries AzLimits (via the MCP tool or the
  single REST search endpoint) about a target Azure service / region / SKU and
  receives relevant limitation records, each carrying source URL, quote,
  confidence, and status, drawn from a seeded dataset of ≥ 93 verified records.

### Secondary
- A human user can call the same REST search endpoint directly (Postman, script,
  CLI) with their token and receive the identical source-backed results.

### Guardrails
- No public result is ever returned without source provenance (source URL + quote)
  and a confidence / verification state — a result without provenance is a defect.
- No protected data is returned without a valid, unexpired token AND active Demo
  license.
- No secrets or tokens appear in any log.

## User Stories

### US-01: Agent checks Azure limitations before generating IaC

- **Given** an AI agent configured with a valid AzLimits token for a Demo-licensed user
- **When** the agent queries the AzLimits MCP tool about a target Azure service before emitting IaC
- **Then** it receives the relevant limitation records, each with source URL, quote, confidence, and status, and can warn the user or adjust the IaC

#### Acceptance Criteria
- The response is rejected if the token is missing, expired, or the license is inactive.
- Every returned record carries source provenance (URL + quote) and a confidence / verification state.
- An empty match returns an explicit empty result, not an error.

### US-02: Developer onboards and generates a token

- **Given** a developer who has not used AzLimits before
- **When** they log in with GitHub, accept the EULA, and request an API token
- **Then** a Demo license is assigned and a token is issued (shown once), usable immediately against the REST search endpoint and the MCP tool

#### Acceptance Criteria
- A token cannot be generated before the EULA is accepted.
- The raw token is displayed once and stored only as a hash.
- Token generation, EULA acceptance, and license assignment are recorded in the audit trail.

## Functional Requirements

### Authentication & Licensing
- FR-001: User can authenticate with GitHub OAuth. Priority: must-have
  > Socrates: Counter-argument considered: "GitHub-only excludes non-GitHub developers." Resolution: kept for MVP — GitHub OAuth is the single identity path; other IdPs are a v2 concern (routed to Open Questions).
- FR-002: User can accept the EULA. Priority: must-have
  > Socrates: Counter-argument considered: "click-through EULA has weak legal value for a demo." Resolution: kept — the EULA is a product + audit gate (acceptance is recorded), independent of its legal strength, which is out of scope for the MVP.
- FR-003: User is assigned a Demo license after accepting the EULA. Priority: must-have
  > Socrates: Counter-argument considered: "a license abstraction is premature with only one tier." Resolution: kept — the Demo license is the seam future tiers hang off; the MVP implementation stays minimal (single tier, checked per request).
- FR-004: User can generate an API token (stored only as a hash). Priority: must-have
  > Socrates: Counter-argument considered: "long-lived tokens are redundant if an OAuth session exists." Resolution: stands — agents need non-interactive tokens; OAuth sessions don't serve the agent path.
- FR-005: User can expire an API token. Priority: must-have
  > Socrates: Counter-argument considered: "revocation UI is scope creep for v1 — expiry alone may suffice." Resolution: split — token *expiration* stays must-have; explicit user-initiated *revocation* demoted to nice-to-have (see FR-005b).
- FR-005b: User can revoke an API token before it expires. Priority: nice-to-have
- FR-006: System validates token validity and Demo license state before every protected response. Priority: must-have
  > Socrates: Counter-argument considered: "per-call license validation is overkill vs checking at token issue." Resolution: stands — license state can change mid-token-life (expiry/revocation), so it must be checked per request.

### Limitation Query
- FR-007: Agent can query limitations through an MCP tool. Priority: must-have
  > Socrates: Counter-argument considered: "MCP is niche — REST-first reaches more users." Resolution: stands — the agent via MCP is the primary persona; MCP is the differentiating surface.
- FR-008: User can search limitations through a single REST search endpoint. Priority: must-have
  > Socrates: Counter-argument considered: "if MCP is primary, REST is redundant for v1." Resolution: stands — REST serves the secondary human persona and is the testing surface for the shared query core.
- FR-009: User can filter limitation search by Azure region and SKU. Priority: nice-to-have
  > Socrates: Counter-argument considered: "region/SKU is the differentiator — demoting it guts core value." Resolution: kept as nice-to-have — service/category search proves v1; region/SKU precision is a fast follow. Flagged in Open Questions as the highest-value v1.1 upgrade.
- FR-010: Each result includes source URL, source title, quote, confidence, status, and verification metadata. Priority: must-have
  > Socrates: Counter-argument considered: "full quote per result bloats responses." Resolution: stands — provenance (URL + quote) is the product's guardrail; without it a result is worthless.
- FR-016: User or agent can check the support status of an Azure service (optionally scoped by region / SKU) and receive supported / unsupported / constrained with backing records. Priority: must-have
  > Note: thin convenience over the same query core as FR-008 — not a separately designed mechanism.
  > Socrates: Counter-argument considered: "duplicates search — agents can infer status." Resolution: stands — a direct yes/no is materially higher-value for an agent making a go/no-go IaC decision.

### Data & Provenance
- FR-011: Operator can import a curated dataset of ≥ 93 verified limitation records into the query database. Priority: must-have
  > Socrates: Counter-argument considered: "93 records is too thin / the CSV may be stale." Resolution: stands — 93 verified, source-backed records beat a larger unverified set for a demo; staleness is tracked via each record's verification metadata.
- FR-012: System serves only approved / verified records through the API and MCP. Priority: must-have
  > Socrates: Counter-argument considered: "gating on 'approved' implies a review workflow not yet scoped." Resolution: kept — for v1, the curated import marks records verified at import time; there is no separate review UI. The review-workflow gap is routed to Open Questions.

### Observability & Audit
- FR-013: System exposes health and readiness endpoints. Priority: must-have
  > Socrates: Counter-argument considered: "standard infra — low priority for a demo." Resolution: stands — required to operate and to satisfy the observability success criterion.
- FR-014: System emits structured logs with correlation IDs for audit, usage, and error events. Priority: nice-to-have
  > Socrates: Counter-argument considered: "structured logging is infra polish, not MVP value." Resolution: demoted — a minimal logging floor (request + error logs, no secrets) moves to NFRs as must-have; full structured/correlated logging becomes nice-to-have for v1.
- FR-015: System records an audit trail for token generation, EULA acceptance, and license checks. Priority: nice-to-have
  > Socrates: Counter-argument considered: "audit trail is compliance-shaped — heavy for a demo." Resolution: demoted to nice-to-have for v1; the minimal record of EULA acceptance (needed by FR-002/FR-003) is retained via the logging floor.

## Non-Functional Requirements

- All traffic is served over HTTPS only.
- User-perceived search / query response is < 800 ms p95 over the seeded dataset.
- Abusive or credential-stuffing request volume is rejected before it reaches
  limitation data, without locking out a legitimate caller.
- No secret or token value ever appears in a log or error response.
- Every public result carries source provenance (URL + quote) and a confidence /
  verification state — no result is returned without proof.
- Stale records are identifiable: each record's verification state and age are
  observable to the consumer.
- Minimal logging floor: every request and error is logged (with secrets
  stripped), sufficient for troubleshooting and to evidence EULA / license events.

## Business Logic

Given a described Azure configuration (a target service, and optionally a region,
SKU, or scenario), AzLimits decides which curated limitations apply to it and
returns them with a support-status verdict and source-backed provenance.

The rule consumes a user-facing intent — the service the user is about to deploy
and, optionally, the region, SKU, or scenario they intend to use. Its output is
the set of applicable limitation records plus a support-status verdict
(supported / unsupported / constrained). Each returned record is accompanied by
its source URL, an exact quote or excerpt, a confidence level, and a verification
state, so the consumer can judge how much to trust it. The user encounters the
rule at decision time: an AI agent invokes it before generating or reviewing IaC
and uses the verdict to warn or adjust; a human invokes the same rule through the
REST search endpoint during design or release planning. The rule is retrieval +
relevance-matching + support-status classification — not a plain record list.

## Access Control

Multi-user, flat role model. A user authenticates with GitHub OAuth, accepts the
EULA, is assigned a Demo license, and generates one or more API tokens. Tokens are
stored only as hashes and support expiration and revocation. Every protected API
response validates both token validity and Demo license state before returning
data; an unauthenticated or unlicensed request is rejected before reaching
limitation data.

- **Roles:** single `user` role for the MVP. There is no in-product admin role.
- **Operator (out-of-band):** ingestion runs and source-registry management are
  performed by the operator outside the product's user-facing access model, using
  least-privilege credentials — not exposed as a product role in the MVP.
- **License:** Demo license only for the MVP; checked on every protected request.
- **Sign-up vs sign-in:** GitHub OAuth is the only identity path. EULA acceptance
  is a hard precondition for token generation.

## Non-Goals

Functional non-goals:
- **No full coverage of all Azure services / every limitation** — the MVP is a
  curated slice; breadth is explicitly not promised.
- **No guarantee that every limitation is detected** — absence from AzLimits does
  not mean absence of a limitation.
- **No automatic remediation or IaC code generation** — AzLimits informs; it does
  not fix or generate infrastructure.
- **No full web dashboard / UI** — API + MCP only for v1.
- **No other clouds (AWS, GCP)** — Azure only.
- **No advanced auth, billing, or enterprise access controls** — GitHub OAuth +
  Demo license only.

Non-functional / operational non-goals:
- **No commitment to a specific LLM provider** — LLM-assisted extraction (a v2
  concern) will not be tied to one vendor.
- **No promise of a fixed source-refresh schedule** — refresh cadence is not an
  MVP guarantee (and live ingestion itself is deferred to v2).
- **No production-grade compliance certifications** — baseline privacy practices
  only; no formal certification.

## Open Questions

1. **Non-GitHub identity** — GitHub OAuth is the only v1 identity path (FR-001). Whether/when to add other IdPs is deferred. Owner: user. Block: no.
2. **"Approved / verified" review workflow** — FR-012 serves only verified records, but v1 has no review UI; the curated import marks records verified at import time. How records get re-verified or re-approved after v2 live ingestion is unresolved. Owner: user. Block: no (v1 uses import-time verification).
3. **Region/SKU precision (FR-009)** — demoted to nice-to-have but is the highest-value v1.1 upgrade, since "supported in region Y with SKU Z" is the sharpest form of the core question. Owner: user. Block: no.
