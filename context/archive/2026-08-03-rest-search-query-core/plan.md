# REST Search Endpoint: Query Core + Provenance + Support-Status Verdict — Implementation Plan

## Overview

Implement S-01, the roadmap's north star: a single protected REST search endpoint that
accepts an Azure service intent, resolves it against the 93-record curated corpus through a
curated alias map, returns only verified records with complete source provenance, and derives
a conservative `supported` / `unsupported` / `constrained` verdict.

This is the smallest end-to-end slice that proves the core product hypothesis — retrieval,
relevance matching, support-status classification, and source-backed provenance, served
through the token + license gate that F-03 already built.

## Current State Analysis

Every prerequisite foundation (F-01 through F-04) is `done`. What exists:

- **Data**: 93 rows in `limitations`, joined 1:N from `sources`. All provenance fields
  (`source_url`, `source_title`, `quote`, `confidence`) are 100% populated, and DB check
  constraints `ck_limitations_quote_not_blank` / `ck_limitations_confidence_not_blank` enforce
  non-blank `quote` and `confidence` at the storage layer.
- **Auth**: `require_active_license` in [auth.py](auth.py) chains `get_current_user`
  (401 paths) and the license check (403 path). One `Depends()` enforces both.
  [main.py](main.py) `/auth/probe` is the reference protected route.
- **Serialization**: nothing. Every route in [main.py](main.py) returns a raw `dict`.
  There are no Pydantic response models anywhere in the project.
- **Tests**: `tests/conftest.py` supplies `clean_test_database`, `auth_db_session`,
  `seeded_user`, `seeded_token`, `seeded_user_no_eula`, `seeded_user_no_license`,
  `seeded_user_inactive_license`. Postgres-only, `TRUNCATE`-based isolation.

What is missing, and what the research established:

- **Exact `service` match is unusable.** 14 distinct `service` values, all human prose
  (`"Azure Blob Storage (SFTP)"`, `"Azure Site Recovery (Scout 8.0.1)"`). The primary
  persona queries `"AKS"`, `"blob storage"`. `WHERE service = :q` matches none of them.
- **The verdict is a design decision, not a lookup.** 8 stored `support_status` values must
  collapse to 3, and 10 of the 14 services return a *mixed* status set that must aggregate
  to one answer.
- **Region/SKU scoping is not implementable.** `region` is populated in 1 of 93 rows (as a
  slash-delimited prose list, not a region code), `sku_tier` in 14 (free-text), `condition`
  in 0. Filtering on them would discard ~99% of the corpus.
- **No fixture seeds an unverified row.** `import_seed` writes `verification_state="verified"`
  for every row, so a query that forgets its verified filter would pass every existing test —
  test-plan's named Risk #2 anti-pattern, verbatim.

## Desired End State

A caller with a valid, unexpired token and an active Demo license can `GET /limitations/search?q=AKS`
and receive HTTP 200 with a payload containing: the echoed query context, a single
`support_status` verdict, and a list of matched limitation records, each carrying a non-empty
`source_url`, `source_title`, `quote`, `confidence`, `support_status`, `verification_state`,
and `verified_at`. A query matching nothing returns 200 with an empty list and a `supported`
verdict. Missing/expired token → 401. Inactive license → 403. No unverified record is ever
returned.

Verify by: `uv run pytest tests/ -v` green (including the new unverified-row leak test), then
manually `curl` the deployed endpoint with a real token for `AKS`, `firewall`, and a nonsense
string, confirming the verdict and provenance in each response.

### Key Discoveries:

- `models.py:32-65` — `Limitation` carries every provenance field plus `verification_state` /
  `verified_at`; `Limitation.source` is the relationship to `sources`.
- `models.py:35-37` — DB-level non-blank check constraints on `quote` and `confidence` already
  guard Risk #1 at the storage layer; the API layer must not weaken that.
- `migrations/versions/20260729_01_create_sources_and_limitations.py:59-64` — `ix_limitations_service`
  and `ix_limitations_verification_state` are the only indexes. No GIN/tsvector, no `pg_trgm`.
  **No migration is needed for this slice** — at 93 rows a sequential scan is microseconds and
  the `< 800 ms p95` NFR does not constrain the matching strategy.
- `auth.py:66-80` — `require_active_license`; `main.py` `/auth/probe` is the copy-paste template.
- `seed.py:28-64` — `SUPPORTED_VALUES["support_status"]` is the authoritative 8-value vocabulary.
  The 8→3 mapping must cover exactly these and nothing else.
- `database.py:11-34` — sessions are synchronous. The new route must be `def`, not `async def`,
  matching every existing route.
- `tests/test_seed_import.py` — `joinedload(Limitation.source)` is the established provenance
  access pattern; without it the response triggers an N+1.
- `tests/test_auth_probe.py` — the 200/401/403 template for a protected route.
- `main.py` and `auth.py` each define their own `SessionFactory` / `get_db`, so two engines
  exist in-process. Pre-existing; out of scope here (see What We're NOT Doing).

## What We're NOT Doing

- **No `region` / `sku` filtering.** The parameters are accepted and echoed back as query
  context; they never reach the `WHERE` clause. FR-009 stays parked.
- **No full-text search, no `pg_trgm`, no `CREATE EXTENSION`, no new index, no migration.**
- **No new Python packages.** Pydantic ships with FastAPI.
- **No `APIRouter`.** The route registers directly on `app`, matching every existing route.
- **No consolidation of the duplicate `SessionFactory` / `get_db`** in [main.py](main.py) and
  [auth.py](auth.py).
- **No MCP surface** — that is S-03.
- **No sorting, grouping, multi-facet filtering, severity ranking, or pagination** — parked as v2.
- **No relevance *scoring*.** Matching is boolean; records are not ranked.
- **No fix for the gitignored seed CSV** (research Open Question #7) — it blocks test-plan
  Phase 5 (CI), not this slice.

## Implementation Approach

Three layers, built inside-out so the interesting logic is testable without HTTP or a database:

1. **A pure query core** (`query.py`) holding the three genuinely decision-bearing functions —
   alias resolution, 8→3 status mapping, and severity-precedence verdict aggregation. These are
   pure functions over plain values, unit-testable with no fixtures.
2. **Response schemas** (`schemas.py`) — the project's first Pydantic models, declaring the
   provenance contract explicitly so the guardrail is visible in the type, not just the test.
3. **A thin route** in [main.py](main.py) that composes them: auth gate → resolve query →
   verified-only DB query with eager-loaded sources → serialize → aggregate verdict.

The critical inversion is that the *verdict* is derived from the *already-filtered, already-verified*
matched set — never from a separate query — so an unverified record cannot influence the answer
even in principle.

## Critical Implementation Details

**Ordering: filter before verdict.** The `verification_state == "verified"` predicate must be
part of the same query whose results feed verdict aggregation. If the verdict were computed from
a broader set and the records filtered afterwards, an unverified `not_supported` row could flip a
service to `unsupported` while remaining invisible in the response — a defect no test in the
plan's suite would catch, because the response body would look correct.

**The empty-match verdict.** Zero matched records must return `supported`, not an error and not a
null verdict. Semantically this is "no known limitation in the corpus" — the PRD's non-goal
("absence from AzLimits does not mean absence of a limitation") means the response must not
overclaim, but US-01's acceptance criterion requires an explicit empty result rather than a 404.

**`supported` does not mean unconstrained.** 27 of the 93 records are `support_status=supported`
and most are `limitation_type=quota_limit` — "supported, with a ceiling". The verdict must never
be presented as an all-clear; the backing records carry the actual constraint.

## Phase 1: Query core + response schemas

### Overview

Build the three pure functions the endpoint's correctness hinges on, plus the Pydantic response
contract, with unit tests that need neither a database nor a `TestClient`.

### Changes Required:

#### 1. Query core module

**File**: `query.py` (new)

**Intent**: Hold the alias map and the three pure decision functions, isolated from FastAPI and
SQLAlchemy so they can be unit-tested directly and reused unchanged by S-03's MCP wrapper.

**Contract**:

- `SERVICE_ALIASES: dict[str, str]` — a module-level constant mapping lowercase agent shorthand
  to the exact stored `service` value. Cover at minimum: `aks`/`kubernetes`/`k8s` →
  `Azure Kubernetes Service`; `blob`/`blob storage`/`sftp` → `Azure Blob Storage (SFTP)`;
  `firewall` → `Azure Firewall`; `functions`/`azure functions` → `Azure Functions`;
  `arm`/`resource manager` → `Azure Resource Manager`; `aca`/`container apps` →
  `Azure Container Apps`; `acr`/`container registry` → `Azure Container Registry`;
  plus entries for the remaining stored services (`Azure Resource Groups`, `Azure Subscriptions`,
  `Azure Local`, `Azure Site Recovery (Scout 8.0.1)`, `Azure Management Groups`, `ARM Templates`,
  `Azure Networking`). Add a one-line comment recording that this map is hand-maintained against
  the 14-service corpus and must be revisited when ingestion widens it.
- `resolve_query(raw: str) -> str | None` — lowercase + strip the input, return the exact stored
  `service` value when an alias hits, otherwise `None` (signalling the caller should fall back to
  substring matching). Returning `None` rather than the raw string keeps the two match modes
  distinguishable at the call site.
- `SUPPORT_STATUS_VERDICTS: dict[str, str]` — the 8→3 mapping. `supported` → `"supported"`;
  `not_supported`, `retired` → `"unsupported"`; `known_issue`, `partially_supported`, `preview`,
  `deprecated`, `support_ticket_required` → `"constrained"`. Keys must be exactly the eight values
  in `seed.py:SUPPORTED_VALUES["support_status"]`.
- `map_support_status(status: str) -> str` — dictionary lookup with an unknown status falling back
  to `"constrained"` rather than raising, so a future ingestion vocabulary change degrades to a
  warning rather than a 500.
- `aggregate_verdict(statuses: Iterable[str]) -> str` — severity precedence: any `"unsupported"` →
  `"unsupported"`; else any `"constrained"` → `"constrained"`; else `"supported"` (including the
  empty-input case).

#### 2. Response schemas

**File**: `schemas.py` (new)

**Intent**: Declare the response contract as Pydantic models — the project's first — so the
provenance guardrail is expressed in types rather than only in assertions.

**Contract**: three models. Pydantic v2 (locked 2.13.4 via FastAPI): use
`model_config = ConfigDict(...)` and `model_dump()`, never inner `class Config` or `.dict()`.

- `LimitationRecord` — `id`, `service`, `feature | None`, `support_status`, `limitation_type`,
  `details | None`, `workaround | None`, `source_url`, `source_title`, `quote`, `confidence`,
  `verification_state`, `verified_at`, `first_seen | None`, `last_seen | None`. The five
  provenance-critical fields (`source_url`, `source_title`, `quote`, `confidence`,
  `verification_state`) are **required and non-optional** — a record that cannot populate them
  cannot be constructed.
- `QueryContext` — `q`, `region | None`, `sku | None`, and a literal note field stating that
  region/SKU are echoed but not applied as filters in v1. This field is what keeps the
  "accept but do not filter" decision from becoming a silent trust bug.
- `SearchResponse` — `query: QueryContext`, `support_status: str`, `record_count: int`,
  `records: list[LimitationRecord]`.

#### 3. Query core unit tests

**File**: `tests/test_query_core.py` (new)

**Intent**: Cover the three pure functions exhaustively — these carry the product decisions, and
they are the cheapest possible place to prove them.

**Contract**: assert `resolve_query` maps `"AKS"`, `"aks"`, `" AKS "`, and `"kubernetes"` to
`"Azure Kubernetes Service"` and returns `None` for an unknown string; assert
`SUPPORT_STATUS_VERDICTS` keys are exactly `seed.SUPPORTED_VALUES["support_status"]` (so adding a
ninth status to the seed vocabulary fails this test loudly); assert `aggregate_verdict` returns
`"unsupported"` for the real Azure Firewall mix, `"constrained"` when constrained is present
without unsupported, `"supported"` for an all-supported set, and `"supported"` for an empty set.

### Success Criteria:

#### Automated Verification:

- Query core unit tests pass: `uv run pytest tests/test_query_core.py -v`
- Full suite still passes: `uv run pytest tests/ -v`
- Linting passes: `uv run ruff check .`
- Type checking passes: `uv run mypy query.py schemas.py`

#### Manual Verification:

- The alias map covers all 14 stored `service` values, with no typos against the exact stored strings
- `SUPPORT_STATUS_VERDICTS` is readable as a product decision at a glance, not buried in branching logic

**Implementation Note**: After completing this phase and all automated verification passes, pause
for manual confirmation before proceeding.

---

## Phase 2: Protected endpoint wiring

### Overview

Register the search route behind the existing auth gate, query verified records with eager-loaded
provenance, and compose the Phase 1 pieces into the response.

### Changes Required:

#### 1. Search route

**File**: [main.py](main.py)

**Intent**: Add the single REST search endpoint (FR-008/FR-016), protected by the same one-line
gate `/auth/probe` uses, returning the composed `SearchResponse`.

**Contract**: `GET /limitations/search`, declared `def` (not `async def`, matching the synchronous
session layer), with:

- `q: str = Query(..., min_length=1)`, `region: str | None = Query(None)`,
  `sku: str | None = Query(None)`
- `user: User = Depends(require_active_license)` and `db: Session = Depends(get_db)` — both with
  the house `# noqa: B008` suppression. Use main.py's own `get_db` (the route lives in main.py);
  do not import auth.py's.
- `response_model=SearchResponse`
- Query construction: `select(Limitation).options(joinedload(Limitation.source))` with
  `Limitation.verification_state == "verified"` **always applied**, plus the match predicate —
  equality on the resolved service when `resolve_query` returns a value, otherwise
  `Limitation.service.ilike(f"%{q}%") | Limitation.feature.ilike(f"%{q}%")`. Bind the pattern as a
  parameter; never interpolate `q` into SQL text.
- Verdict computed by `aggregate_verdict(map_support_status(r.support_status) for r in rows)` over
  the **same** row set that is serialized.
- No match → 200 with `records: []`, `record_count: 0`, `support_status: "supported"`. Never 404,
  never 500.
- Any `HTTPException` raised keeps a static `detail` string with no request data interpolated,
  per the house rule.

#### 2. Endpoint smoke tests

**File**: `tests/test_limitations_search.py` (new)

**Intent**: Prove the auth gate and the basic response shape, mirroring
[tests/test_auth_probe.py](tests/test_auth_probe.py).

**Contract**: no token → 401; expired token → 401; inactive license → 403; valid token + a seeded
limitation row → 200 with a `SearchResponse`-shaped body whose `query.q` echoes the input and whose
`region` / `sku` are echoed unchanged when supplied. Seed limitation rows directly via the ORM in
Construct the client as `TestClient(app, base_url="http://localhost")` — TrustedHostMiddleware
rejects the default `testserver` host with 400. Seeded `quote` / `confidence` must be non-blank
after trim (DB check constraints `ck_limitations_quote_not_blank` /
`ck_limitations_confidence_not_blank` fail at INSERT, not at assertion time). A 500 from the route
surfaces as `{"detail": "Internal Server Error"}` via the global exception handler — check the
captured log for the real traceback, not the response body.
these tests rather than through `import_seed`, so the suite does not depend on the gitignored CSV.

### Success Criteria:

#### Automated Verification:

- Endpoint tests pass: `uv run pytest tests/test_limitations_search.py -v`
- Full suite passes: `uv run pytest tests/ -v`
- Linting passes: `uv run ruff check .`
- Type checking passes: `uv run mypy main.py`

#### Manual Verification:

- `curl` with a real token for `q=AKS` returns Azure Kubernetes Service records and an `unsupported` verdict
- `curl` for `q=zzz-nonexistent` returns 200 with an empty list, not an error
- Passing `region=westeurope` visibly changes only the echoed query context, not the record set
- Request logs show the query path with no token value present

**Implementation Note**: After completing this phase and all automated verification passes, pause
for manual confirmation before proceeding.

---

## Phase 3: Risk-guardrail integration tests

### Overview

Cover test-plan §3 Phase 3 — Risks #1, #2, and #6 — with the specific tests each risk's
"Anti-pattern to avoid" column rules out, then reconcile the foundation docs.

### Changes Required:

#### 1. Provenance guardrail test (Risk #1)

**File**: `tests/test_limitations_search.py`

**Intent**: Prove *every* record in a multi-record response carries non-empty provenance, deriving
expectations from the database rather than from the serializer under test.

**Contract**: seed at least three limitation rows across two sources, query, then assert for
**every** record in the response that `source_url`, `source_title`, `quote`, `confidence`, and
`verification_state` are present and non-empty after `.strip()`. Cross-check each response record's
provenance against the corresponding DB row loaded independently via
`joinedload(Limitation.source)` — not against the response itself. Explicitly avoids asserting one
happy record and avoids the oracle problem named in the test plan.

#### 2. Unverified-record leak test (Risk #2)

**File**: `tests/test_limitations_search.py`

**Intent**: Prove the verified filter is actually applied. Without this the filter could be absent
and every existing test would still pass, because nothing in the codebase writes an unverified row.

**Contract**: insert two rows for the same service by hand — one `verification_state="verified"`,
one `verification_state="unverified"` — with distinguishable `id`s. Assert the response contains
the verified `id` and does **not** contain the unverified `id`. Make the unverified row
`support_status="not_supported"` while the verified row is `supported`, so the test also proves the
excluded row did not leak into the verdict.

#### 3. Empty-match test (Risk #6)

**File**: `tests/test_limitations_search.py`

**Intent**: Prove a no-match query is a clean empty result, not an error.

**Contract**: with the tables clean, query a nonsense string and assert `status_code == 200`,
`records == []`, `record_count == 0`, and `support_status == "supported"`.

#### 4. Foundation doc reconciliation

**File**: [context/foundation/test-plan.md](context/foundation/test-plan.md)

**Intent**: Record that Phase 3's coverage landed inside S-01 rather than as its own testing change,
and fill in the cookbook section it left as TBD.

**Contract**: in §3, set Phase 3 Status to `complete` and its Change folder to
`context/changes/rest-search-query-core/`. Replace §6.5's "TBD — see §3 Phase 3" with the concrete
pattern: seed rows via the ORM (not `import_seed`), assert non-empty provenance on every record
against independently-loaded DB rows, always include an unverified row when testing a
verified-filtered query, and assert 200-with-empty-list for the no-match path.

**File**: [context/foundation/roadmap.md](context/foundation/roadmap.md)

**Intent**: Close S-01 and record the answer to Open Roadmap Question #4.

**Contract**: set S-01's Status to `done` in both the "At a glance" table and the S-01 slice
section; resolve Open Roadmap Question #4 with the chosen answer (curated alias map + substring
fallback on `service`/`feature`; no relevance scoring); annotate the FR-016 region/SKU note so the
accept-but-do-not-filter behaviour is recorded as a deliberate data-driven decision rather than
read later as a defect.

### Success Criteria:

#### Automated Verification:

- All risk-guardrail tests pass: `uv run pytest tests/test_limitations_search.py -v`
- Full suite passes: `uv run pytest tests/ -v`
- Linting passes: `uv run ruff check .`
- Type checking passes: `uv run mypy .`

#### Manual Verification:

- Temporarily deleting the `verification_state == "verified"` predicate makes the Risk #2 test fail
  (the test genuinely observes the leak rather than passing vacuously)
- Deployed endpoint verified end-to-end with a real token against the live Neon dataset
- test-plan §3 and roadmap S-01 statuses match what actually shipped

---

## Testing Strategy

### Unit Tests:

- `resolve_query` alias hits, case/whitespace insensitivity, and the `None` fallback
- `SUPPORT_STATUS_VERDICTS` key-set equality with `seed.SUPPORTED_VALUES["support_status"]`
- `aggregate_verdict` severity precedence, including the empty-set case

### Integration Tests:

- 401 (no token), 401 (expired token), 403 (inactive license), 200 (valid) on the search route
- Non-empty provenance on every record of a multi-record response, cross-checked against the DB
- An unverified row is excluded from both the record list and the verdict
- A no-match query returns 200 with an empty list

### Manual Testing Steps:

1. `curl -H "Authorization: Bearer <token>" ".../limitations/search?q=AKS"` — expect Azure
   Kubernetes Service records and an `unsupported` verdict
2. Repeat with `q=firewall` — expect `unsupported` (12 of 18 records are `not_supported`)
3. Repeat with `q=Azure%20Resource%20Groups` — expect `supported` (all 7 records are `supported`)
4. Repeat with `q=zzz-nonexistent` — expect 200, empty list, `supported`
5. Repeat with `q=AKS&region=westeurope&sku=Standard` — expect the same record set, with the
   parameters echoed in the query context
6. Repeat without a token — expect 401 and no record data in the body
7. Check the request logs for the above calls — expect the path logged and no token value present

## Performance Considerations

At 93 rows every match strategy is a sub-millisecond sequential scan, so the `< 800 ms p95` NFR is
not a constraint on any decision here. The only real risk is the N+1 that appears if `source` is
lazy-loaded per record — `joinedload(Limitation.source)` is mandatory, not an optimization.

## Migration Notes

None. This slice adds no columns, no indexes, and no extensions. The existing
`ix_limitations_service` and `ix_limitations_verification_state` are sufficient, and no Alembic
revision is created.

## References

- Research: [context/changes/rest-search-query-core/research.md](context/changes/rest-search-query-core/research.md)
- Roadmap slice S-01: [context/foundation/roadmap.md](context/foundation/roadmap.md)
- Risk map and Risk Response Guidance: [context/foundation/test-plan.md](context/foundation/test-plan.md)
- Protected-route template: `main.py` `/auth/probe`
- Auth gate: `auth.py:36-63`, `auth.py:66-80`
- Provenance access pattern: `tests/test_seed_import.py`
- Status vocabulary: `seed.py:28-64`
- Prior slice that parked this work: [context/archive/2026-07-29-postgres-schema-seed/plan.md](context/archive/2026-07-29-postgres-schema-seed/plan.md)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Query core + response schemas

#### Automated

- [x] 1.1 Query core unit tests pass: `uv run pytest tests/test_query_core.py -v` — 1beb5d2
- [x] 1.2 Full suite still passes: `uv run pytest tests/ -v` — 1beb5d2
- [x] 1.3 Linting passes: `uv run ruff check .` — 1beb5d2
- [x] 1.4 Type checking passes: `uv run mypy query.py schemas.py` — 1beb5d2

#### Manual

- [x] 1.5 Alias map covers all 14 stored `service` values with no typos — 1beb5d2
- [x] 1.6 `SUPPORT_STATUS_VERDICTS` is readable as a product decision at a glance — 1beb5d2

### Phase 2: Protected endpoint wiring

#### Automated

- [x] 2.1 Endpoint tests pass: `uv run pytest tests/test_limitations_search.py -v` — 8733f6e
- [x] 2.2 Full suite passes: `uv run pytest tests/ -v` — 8733f6e
- [x] 2.3 Linting passes: `uv run ruff check .` — 8733f6e
- [x] 2.4 Type checking passes: `uv run mypy main.py` — 8733f6e

#### Manual

- [x] 2.5 `q=AKS` returns AKS records with an `unsupported` verdict — 8733f6e
- [x] 2.6 `q=zzz-nonexistent` returns 200 with an empty list — 8733f6e
- [x] 2.7 `region` changes only the echoed query context, not the record set — 8733f6e
- [x] 2.8 Request logs show the query path with no token value present — 8733f6e

### Phase 3: Risk-guardrail integration tests

#### Automated

- [x] 3.1 All risk-guardrail tests pass: `uv run pytest tests/test_limitations_search.py -v` — 2f7b94a
- [x] 3.2 Full suite passes: `uv run pytest tests/ -v` — 2f7b94a
- [x] 3.3 Linting passes: `uv run ruff check .` — 2f7b94a
- [x] 3.4 Type checking passes: `uv run mypy .` — 2f7b94a

#### Manual

- [x] 3.5 Removing the verified filter makes the Risk #2 test fail — 2f7b94a
- [x] 3.6 Deployed endpoint verified end-to-end against the live Neon dataset — 2f7b94a
- [x] 3.7 test-plan §3 and roadmap S-01 statuses match what shipped — 2f7b94a
