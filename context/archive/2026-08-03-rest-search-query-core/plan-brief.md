# REST Search Endpoint: Query Core + Provenance + Support-Status Verdict — Plan Brief

> Full plan: `context/changes/rest-search-query-core/plan.md`
> Research: `context/changes/rest-search-query-core/research.md`

## What & Why

S-01 is the roadmap's north star — the smallest end-to-end slice that proves the core product
hypothesis. It adds a single protected REST search endpoint where an AI agent (or a human with a
token) asks about an Azure service and gets back the applicable curated limitations, each with
source provenance, plus a one-word `supported` / `unsupported` / `constrained` verdict it can act on
before emitting IaC. Everything else in the product only matters if this works.

## Starting Point

All four foundations are `done`: 93 verified records sit in Neon Postgres with 100%-populated
provenance fields, `require_active_license` gives a one-line token+license gate, and logging
middleware strips secrets. What's missing is the query itself — plus the project's first Pydantic
response model, since every existing route returns a raw `dict`. Research profiled the corpus and
found the two assumptions baked into the earlier schema slice to be weaker than they looked: exact
`service` match can't serve the primary persona, and `region` / `sku_tier` are too sparse to filter on.

## Desired End State

`GET /limitations/search?q=AKS` with a valid token returns HTTP 200 carrying the matched Azure
Kubernetes Service records — every one with a non-empty source URL, title, quote, confidence, and
verification state — alongside an `unsupported` verdict. A nonsense query returns 200 with an empty
list, never an error. No unverified record ever appears in a response or influences a verdict.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Matching strategy | Curated ~14-entry alias map, falling back to substring on `service` + `feature` | The 14 stored services are human prose (`"Azure Blob Storage (SFTP)"`) while agents say `"AKS"` — and excluding `quote` from the match surface avoids low-precision hits that would corrupt the verdict | Plan |
| 8→3 status mapping | Only `supported` maps to supported; `not_supported`/`retired` → unsupported; the other five → constrained | Reporting a preview or deprecated feature as flatly supported is exactly the failure the product exists to prevent | Plan |
| Verdict aggregation | Severity precedence: `unsupported` > `constrained` > `supported` | Majority vote would report AKS as supported while 4 unsupported records sit in the payload — a false all-clear on a go/no-go decision | Plan |
| Region / SKU (FR-016) | Accept the params, echo them in the response, never filter on them | `region` is populated in 1 of 93 rows and `sku_tier` in 14, both free-text — filtering would silently discard ~99% of the corpus | Research + Plan |
| Code placement | `query.py` (logic) + `schemas.py` (models); route stays in `main.py` | Makes the three decision-bearing functions unit-testable without HTTP or a DB, without introducing the project's first `APIRouter` | Plan |
| Test scope | Fold test-plan Phase 3 (Risks #1/#2/#6) into this change | No fixture seeds an unverified row today, so a missing verified filter would pass every existing test — shipping the north star unguarded isn't acceptable | Plan |
| Indexes / migration | None | At 93 rows a sequential scan is microseconds; the `< 800 ms p95` NFR doesn't constrain the design | Research |

## Scope

**In scope:**
- `query.py` — alias map, `resolve_query`, `map_support_status`, `aggregate_verdict`
- `schemas.py` — `LimitationRecord`, `QueryContext`, `SearchResponse`
- `GET /limitations/search` in `main.py` behind `Depends(require_active_license)`
- Unit tests for the query core; integration tests for auth, provenance, unverified-leak, empty-match
- test-plan §3/§6.5 and roadmap S-01 reconciliation

**Out of scope:**
- Region/SKU filtering (FR-009, parked), full-text search, `pg_trgm`, any migration or new index
- New Python packages, `APIRouter`, consolidating the duplicate `get_db` in `main.py` / `auth.py`
- MCP wrapper (S-03), sorting/grouping/pagination/relevance scoring (v2)

## Architecture / Approach

Three layers, built inside-out. A pure query core holds the alias map and the three functions that
carry the product decisions — no FastAPI, no SQLAlchemy, so they unit-test with no fixtures and S-03
can reuse them unchanged. Pydantic schemas declare the provenance contract in types. A thin route
composes them: auth gate → resolve query → single verified-only SQLAlchemy query with
`joinedload(Limitation.source)` → serialize → aggregate the verdict **from that same filtered row
set**. That last inversion is load-bearing: computing the verdict from the already-filtered records
means an unverified row can't influence the answer even in principle.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Query core + schemas | `query.py`, `schemas.py`, and pure unit tests needing no DB | Alias map typos against the exact stored service strings silently return zero matches |
| 2. Endpoint wiring | `GET /limitations/search` behind the auth gate, with 401/403/200 smoke tests | Forgetting `joinedload` produces an N+1 that only shows under real data volume |
| 3. Risk-guardrail tests | Provenance (#1), unverified-leak (#2), empty-match (#6) coverage + doc reconciliation | A leak test that passes vacuously because the unverified row was never actually inserted |

**Prerequisites:** F-01, F-02, F-03, F-04 — all `done`. A reachable `TEST_DATABASE_URL` Postgres for
the integration tests.
**Estimated effort:** ~2-3 sessions across 3 phases; no migration, no new dependencies.

## Open Risks & Assumptions

- The alias map is hand-maintained against a 14-service corpus. It is correct today and rots the
  moment v2 ingestion widens the dataset — the plan records this in a comment, but it needs an owner.
- `constrained` is a five-value catch-all covering 28 records with genuinely different meanings
  (preview, deprecation, known issue, ticket-required). The verdict alone under-informs; the agent
  must read the backing records.
- Severity precedence means most broad queries return `unsupported`. If that proves too noisy in
  real agent use, the fallback is adding per-verdict counts — a purely additive response change.
- A `supported` verdict is not an all-clear: 27 of the 93 records are `supported` quota limits.
- `first_seen` / `last_seen` are identical across all 93 rows, so the NFR on staleness is satisfied
  by *surfacing* the fields only — there is no real staleness signal in v1 data to build logic on.

## Success Criteria (Summary)

- An authenticated, Demo-licensed caller queries a service by agent shorthand (`AKS`) and receives
  matching records plus a verdict — the PRD's Primary success criterion, met end-to-end.
- Every returned record carries non-empty source URL, title, quote, confidence, and verification
  state; a record without provenance is impossible to construct.
- An empty match is an explicit empty result at HTTP 200, and an unverified record never appears.
