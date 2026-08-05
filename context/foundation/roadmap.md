---
project: "AzLimits"
version: 1
status: draft
created: 2026-07-20
updated: 2026-08-03
prd_version: 1
main_goal: quality
top_blocker: time
---

# Roadmap: AzLimits (Azure Oracle)

> Derived from `context/foundation/prd.md` (v1) + auto-researched codebase baseline.
> Edit-in-place; archive when superseded.
> Slices below are listed in dependency order. The "At a glance" table is the index.

## Vision recap

Azure design and IaC decisions are committed up front, but the limitations that
invalidate those choices (quotas, hard limits, unsupported scenarios, known issues,
preview caveats, deprecations, regional / SKU / networking / identity / tooling
constraints) are discovered late — during implementation, deployment, or release
hardening. The cost is redesign, deployment failures, release delays, and
unsupported architecture decisions. This information already exists but is trapped
and scattered across Microsoft docs, quota pages, troubleshooting articles, GitHub
repositories, and public issue trackers. AzLimits delivers it inline — to an AI
agent at the moment it generates or reviews IaC — as a single, structured,
source-backed dataset the agent can query before committing.

## North star

**S-01: Human queries limitations via REST search endpoint** — the smallest
end-to-end slice whose successful delivery would prove the core product hypothesis
(retrieval + relevance-matching + support-status classification + source-backed
provenance, served through a protected endpoint).

> "North star" here means the smallest end-to-end slice whose successful delivery
> would prove the core product hypothesis — placed as early as Prerequisites allow
> because everything else only matters if this works. The user chose to validate
> the query core through the simpler human REST surface first (PRD §Success
> Criteria Primary explicitly allows "via the MCP tool or the single REST search
> endpoint"); the MCP wrapper (S-03) lands as a follow-on, not the validation
> milestone.

## At a glance

| ID | Change ID | Outcome (user can …) | Prerequisites | PRD refs | Status |
|---|---|---|---|---|---|
| F-01 | deploy-skeleton-health | (foundation) deployable FastAPI app + `/health` + readiness + Railway config | — | FR-013, NFR (HTTPS) | done |
| F-02 | postgres-schema-seed | (foundation) external Neon Postgres wired, limitations schema, curated CSV import (≥93 verified records) | — | FR-011, FR-012 | done |
| F-03 | auth-scaffold-token-license | (foundation) GitHub OAuth + EULA + Demo license + token hashing + per-request token+license validation middleware | — | FR-001, FR-002, FR-003, FR-004, FR-005, FR-006 | done |
| F-04 | observability-logging-floor | (foundation) request/error logging middleware with secrets stripped | — | NFR (minimal logging floor), FR-013 | done |
| S-01 | rest-search-query-core | user can query limitations via the REST search endpoint and receive source-backed records with a support-status verdict | F-01, F-02, F-03, F-04 | US-01, FR-008, FR-010, FR-016, FR-006 | done |
| S-02 | developer-onboarding-token | user can log in with GitHub, accept EULA, get Demo license, generate/expire a token | F-03 | US-02, FR-001, FR-002, FR-003, FR-004, FR-005 | proposed |
| S-03 | mcp-tool-wrapper | agent can query the same query core through an MCP tool | S-01 | US-01, FR-007 | proposed |

## Streams

Navigation aid — groups items that share a Prerequisites chain. Canonical ordering still lives in the dependency graph below; this table is the proposed reading order across parallel tracks.

| Stream | Theme | Chain | Note |
|---|---|---|---|
| A | Deploy & query core | `F-01` → `F-04` → `S-01` → `S-03` | The `quality` main_goal biases toward eager observability (F-04) before the user-facing query slice. |
| B | Data seed | `F-02` | Joins Stream A at `S-01` — the query core needs seeded data to return. |
| C | Auth & onboarding | `F-03` → `S-02` | Joins Stream A at `S-01` via `F-03` (the protected endpoint's token+license gate); `S-02` runs parallel with `S-01`. |

## Baseline

What's already in place in the codebase as of 2026-07-20 (auto-researched + user-confirmed).
Foundations below assume these are present and do NOT re-scaffold them.

- **Frontend:** absent — no UI layer (PRD §Non-Goals: "No full web dashboard / UI — API + MCP only for v1")
- **Backend / API:** partial — FastAPI + uvicorn in `pyproject.toml`; `main.py` is hello-world stub, no `app` object, no routes (per `tech-stack.md`: FastAPI + uvicorn + uv declared)
- **Data:** absent — no DB driver, ORM, migration tooling, or seeded data wired
- **Auth:** absent — no OAuth, token, or license code paths
- **Deploy / infra:** partial — `.python-version` pinned to 3.12, `uv.lock` committed; no Dockerfile/railway.json/.github/workflows (per `infrastructure.md` + `deploy-plan.md`: Railway + external Neon Postgres declared, manual `railway up` path documented as follow-up)
- **Observability:** absent — no logging middleware, error tracking, or metrics

## Foundations

### F-01: Deploy skeleton + health/readiness

- **Outcome:** (foundation) a deployable FastAPI `app` object exists at `main:app`, `/health` and readiness endpoints respond, Railway config (start command, health-check host in allowed hosts) is in place — the smallest skeleton that can be deployed and verified.
- **Change ID:** deploy-skeleton-health
- **PRD refs:** FR-013 (health + readiness endpoints), NFR (HTTPS-only), `deploy-plan.md` §1 Entry Gates
- **Unlocks:** S-01 (the REST query endpoint needs a deployed app to be exercised end-to-end); provides the verification path (`/health`) that Railway's health check gates on.
- **Prerequisites:** —
- **Parallel with:** F-02, F-03, F-04 (no inter-foundation dependencies)
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Sequenced first because it is the smallest foundation and creates the verification surface every downstream slice relies on. Risk: if the Railway health-check host is not added to FastAPI allowed hosts, zero-downtime deploys fail in a way that looks like an app bug (per `infrastructure.md` unknown-unknowns).
- **Status:** done

### F-02: External Postgres + schema + seeded import

- **Outcome:** (foundation) external Neon Postgres wired as `DATABASE_URL`, limitations + sources schema in place, the curated `concept/azure_limitations_db.csv` imported as ≥93 verified records with import-time verification metadata — the minimum data contract the query core can retrieve from.
- **Change ID:** postgres-schema-seed
- **PRD refs:** FR-011 (≥93 verified records import), FR-012 (verified-only serving), FR-010 (provenance fields per record)
- **Unlocks:** S-01 (the query core needs data to return); reduces the "unmanaged DB loses provenance dataset" risk by using external managed Postgres with automated backups (per `infrastructure.md` risk register).
- **Prerequisites:** —
- **Parallel with:** F-01, F-03, F-04
- **Blockers:** —
- **Unknowns:**
  - Is the curated CSV schema-aligned with the limitations + sources schema, or does it need a normalization step? — Owner: user. Block: no (resolvable during `/10x-plan`).
- **Risk:** Sequenced as a parallel foundation because data is on the critical path of S-01 but has no dependency on auth or deploy skeleton. Risk: if the CSV is stale or schema-mismatched, S-01 returns thin results — mitigated by FR-011's "93 verified, source-backed records beat a larger unverified set" resolution and per-record verification metadata.
- **Status:** done

### F-03: Auth scaffold + token/license validation middleware

- **Outcome:** (foundation) GitHub OAuth callback, EULA acceptance record, Demo license assignment, API token generation (stored hash-only), and per-request token-validity + Demo-license-state validation middleware — the smallest auth contract that lets a protected endpoint proceed.
- **Change ID:** auth-scaffold-token-license
- **PRD refs:** FR-001 (GitHub OAuth), FR-002 (EULA), FR-003 (Demo license), FR-004 (token generation, hash-only), FR-005 (token expiration), FR-006 (per-request token + license validation), PRD §Access Control
- **Unlocks:** S-01 (the protected REST endpoint needs the token+license gate); S-02 (onboarding flow exercises this scaffold through a real user capability).
- **Prerequisites:** —
- **Parallel with:** F-01, F-02, F-04
- **Blockers:** —
- **Unknowns:** —
- **Risk:** This is the largest foundation because the PRD makes all of auth must-have and the Access Control section is non-trivial (multi-user, token hashing, per-request license validation). It is NOT "the auth layer complete" — S-02 still exercises OAuth + EULA + license + token issuance through a real user-visible onboarding flow, and FR-005b (revocation) is Parked. Risk: if per-request license validation is skipped or cached, the guardrail "No protected data without active Demo license" is violated — sequenced eagerly per the `quality` main_goal.
- **Status:** done

### F-04: Observability floor + secrets-stripped logging

- **Outcome:** (foundation) request + error logging middleware with secrets stripped from logs and error bodies — the minimal logging floor the PRD NFR requires.
- **Change ID:** observability-logging-floor
- **PRD refs:** NFR (minimal logging floor: every request + error logged, secrets stripped), FR-013 (health endpoints — already in F-01), FR-014 (nice-to-have full structured logging — Parked)
- **Unlocks:** S-01 (provenance + license events need logging evidence; the "no secrets in logs" guardrail needs the stripping middleware); reduces the "secrets/tokens leak into logs" risk from `infrastructure.md` risk register.
- **Prerequisites:** —
- **Parallel with:** F-01, F-02, F-03
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Sequenced eagerly (before S-01) per the `quality` main_goal — the "no secrets or tokens appear in any log" guardrail is a launch gate, not polish. Risk: if the stripping middleware is added after S-01 ships, a secret leak during the first end-to-end exercise is uncaught. Full structured/correlated logging (FR-014) is Parked, not deferred late.
- **Status:** done

## Slices

### S-01: Human queries limitations via REST search endpoint

- **Outcome:** user can call the single REST search endpoint with a valid token + active Demo license and receive the relevant limitation records, each with source URL, source title, quote, confidence, status, and verification metadata, plus a support-status verdict (supported / unsupported / constrained).
- **Change ID:** rest-search-query-core
- **PRD refs:** US-01, FR-008 (single REST search endpoint), FR-010 (provenance per result), FR-016 (support-status check), FR-006 (per-request token + license validation)
- **Prerequisites:** F-01 (deploy skeleton), F-02 (seeded data), F-03 (auth gate), F-04 (logging floor)
- **Parallel with:** S-02 (both depend only on F-03; neither blocks the other)
- **Blockers:** —
- **Unknowns:**
  - Does the query core need a relevance-matching algorithm beyond exact service/category match for v1, or is exact-match + support-status classification sufficient? — Owner: user. Block: no (resolvable during `/10x-plan`; PRD §Business Logic says "retrieval + relevance-matching + support-status classification" but does not specify the matching algorithm).
- **Risk:** This is the north star — the validation milestone (the smallest end-to-end slice whose successful delivery proves the core product hypothesis). Risk: if the query core returns records without provenance or serves unverified records, the PRD §Guardrails ("No public result is ever returned without source provenance") is violated — mitigated by F-02 (import-time verification) and F-04 (logging evidence).
- **Status:** done

### S-02: Developer onboards and generates a token

- **Outcome:** user can log in with GitHub OAuth, accept the EULA, be assigned a Demo license, and generate (and expire) an API token shown once and stored only as a hash, usable immediately against the REST search endpoint and the MCP tool.
- **Change ID:** developer-onboarding-token
- **PRD refs:** US-02, FR-001 (GitHub OAuth), FR-002 (EULA), FR-003 (Demo license), FR-004 (token generation, hash-only), FR-005 (token expiration)
- **Prerequisites:** F-03 (auth scaffold — this slice exercises it through a real user capability)
- **Parallel with:** S-01
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Sequenced parallel with S-01 because both depend only on F-03; neither blocks the other. Risk: if the raw token is displayed more than once or stored unhashed, the PRD §Guardrails ("No secrets or tokens appear in any log") and US-02 AC ("raw token displayed once and stored only as a hash") are violated — mitigated by F-03's hash-only contract and F-04's secret-stripping middleware.
- **Status:** proposed

### S-03: Agent queries limitations via MCP tool

- **Outcome:** an AI agent can query the same query core through an MCP tool and receive the identical source-backed limitation records with a support-status verdict.
- **Change ID:** mcp-tool-wrapper
- **PRD refs:** US-01, FR-007 (MCP tool query)
- **Prerequisites:** S-01 (the query core must exist before wrapping as MCP)
- **Parallel with:** —
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Sequenced after S-01 (the north star) because the MCP wrapper is a thin surface over the already-validated query core — wrapping before the core is proven would couple two risks. Risk: if the MCP tool returns results without the token+license gate, the PRD §Access Control guardrail is violated — mitigated by reusing F-03's middleware.
- **Status:** proposed

## Backlog Handoff

| Roadmap ID | Change ID | Suggested issue title | Ready for `/10x-plan` | Notes |
|---|---|---|---|---|
| F-01 | deploy-skeleton-health | Deploy skeleton: FastAPI app + /health + Railway config | yes | Prerequisites: none — but all four foundations should be planned together since S-01 depends on all of them. |
| F-02 | postgres-schema-seed | External Postgres + schema + curated CSV import (≥93 verified records) | yes | — |
| F-03 | auth-scaffold-token-license | Auth scaffold: GitHub OAuth + EULA + Demo license + token hashing + per-request validation | yes | Largest foundation; S-02 exercises it end-to-end. |
| F-04 | observability-logging-floor | Observability floor: request/error logging middleware with secret stripping | yes | — |
| S-01 | rest-search-query-core | REST search endpoint: query core + provenance + support-status verdict | no | North star. Run `/10x-plan rest-search-query-core` after F-01–F-04 land. |
| S-02 | developer-onboarding-token | Developer onboarding: GitHub login + EULA + Demo license + token generation/expiration | no | Parallel with S-01. |
| S-03 | mcp-tool-wrapper | MCP tool wrapper over the query core | no | After S-01. |

## Open Roadmap Questions

1. **Non-GitHub identity** — GitHub OAuth is the only v1 identity path (FR-001). Whether/when to add other IdPs is deferred. Owner: user. Block: no.
2. **"Approved / verified" review workflow** — FR-012 serves only verified records, but v1 has no review UI; the curated import marks records verified at import time. How records get re-verified or re-approved after v2 live ingestion is unresolved. Owner: user. Block: no (v1 uses import-time verification).
3. **Region/SKU precision (FR-009)** — demoted to nice-to-have but is the highest-value v1.1 upgrade, since "supported in region Y with SKU Z" is the sharpest form of the core question. Owner: user. Block: no.
4. **Query-core relevance matching** — **Resolved for v1:** a hand-maintained curated alias map resolves known service shorthand, with a case-insensitive substring fallback across `service` and `feature`; no relevance scoring. This keeps matching explainable and sufficient for the 93-record corpus. Region and SKU remain accepted and echoed only, never applied as filters, because the available corpus data is too sparse and free-form for reliable filtering (FR-009 remains parked).

## Parked

- **FR-005b: token revocation (nice-to-have)** — Why parked: PRD split expiration (must-have) from revocation (nice-to-have); the `time` main_goal parks nice-to-haves aggressively. Revisit in v1.1.
- **FR-009: region/SKU filter (nice-to-have)** — Why parked: PRD demoted to nice-to-have; flagged as the highest-value v1.1 upgrade (Open Roadmap Question #3). Service/category search proves v1.
- **FR-014: full structured/correlated logging (nice-to-have)** — Why parked: PRD demoted; the minimal logging floor (F-04) is must-have and stays. Full structured logging is v1.1.
- **FR-015: audit trail (nice-to-have)** — Why parked: PRD demoted; the minimal record of EULA acceptance (needed by FR-002/FR-003) is retained via F-04's logging floor. Full audit trail is v1.1.
- **v2: automated/scheduled source ingestion** — Why parked: `shape-notes.md` §Forward: v2 — live ingestion deferred; v1 seeds from the curated CSV.
- **v2: LLM-assisted extraction** — Why parked: `shape-notes.md` §Forward: v2 — curated seed data needs no extraction.
- **v2: rich REST query surface (sorting, grouping, multi-facet filtering, severity)** — Why parked: `shape-notes.md` §Forward: v2 — v1 ships one query core + one REST endpoint.
- **v2: optional surfaces (web UI, CLI, GitHub Action, VS Code / Copilot integration, JSONL export)** — Why parked: `shape-notes.md` §Forward: v2 — v1 is API + MCP only.
- **CI/CD: GitHub Actions auto-deploy-on-merge** — Why parked: `deploy-plan.md` §Decisions — manual `railway up` for the first deploy; CI auto-deploy is a documented follow-up, not a v1 slice.

## Done

- **S-01: user can query limitations via the REST search endpoint and receive source-backed records with a support-status verdict.** — Completed 2026-08-05 → `context/changes/rest-search-query-core/`.
- **F-01: (foundation) a deployable FastAPI `app` object exists at `main:app`, `/health` and readiness endpoints respond, Railway config (start command, health-check host in allowed hosts) is in place — the smallest skeleton that can be deployed and verified.** — Archived 2026-07-29 → `context/archive/2026-07-20-deploy-skeleton-health/`. Lesson: —.
- **F-02: (foundation) external Neon Postgres wired, limitations schema, curated CSV import (≥93 verified records) — the minimum data contract the query core can retrieve from.** — Archived 2026-07-29 → `context/archive/2026-07-29-postgres-schema-seed/`. Lesson: —.
- **F-04: (foundation) request + error logging middleware with secrets stripped from logs and error bodies — the minimal logging floor the PRD NFR requires.** — Archived 2026-08-03 → `context/archive/2026-08-02-observability-logging-floor/`. Lesson: —.
- **F-03: (foundation) GitHub OAuth callback, EULA acceptance record, Demo license assignment, API token generation (stored hash-only), and per-request token-validity + Demo-license-state validation middleware — the smallest auth contract that lets a protected endpoint proceed.** — Archived 2026-08-03 → `context/archive/2026-07-29-auth-scaffold-token-license/`. Lesson: —.
