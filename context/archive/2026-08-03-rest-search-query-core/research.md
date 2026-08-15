---
date: 2026-08-03T18:21:53+02:00
researcher: GitHub Copilot
git_commit: 2ae625e771bc63213adbf9de82b15066519122bc
branch: main
repository: patryk-plonka/azure-oracle
topic: "rest-search-query-core: seeded-data shape and matching feasibility for the REST search endpoint (S-01)"
tags: [research, codebase, query-core, seed-data, limitations, support-status, provenance, fastapi]
status: complete
last_updated: 2026-08-03
last_updated_by: GitHub Copilot
---

# Research: rest-search-query-core — seeded-data shape and matching feasibility

**Date**: 2026-08-03T18:21:53+02:00
**Researcher**: GitHub Copilot
**Git Commit**: `2ae625e771bc63213adbf9de82b15066519122bc`
**Branch**: `main`
**Repository**: patryk-plonka/azure-oracle

## Research Question

What must `/10x-plan rest-search-query-core` know before it can specify S-01 — the
single protected REST search endpoint that returns source-backed limitation records
plus a supported / unsupported / constrained verdict?

Focus (user-selected): **seeded-data shape and matching feasibility** — i.e. resolve
Open Roadmap Question #4, *"Does the query core need a relevance-matching algorithm
beyond exact service/category match for v1, or is exact-match + support-status
classification sufficient?"* ([context/foundation/roadmap.md](context/foundation/roadmap.md))

## Summary

The seeded dataset — 93 rows, profiled directly from
[concept/azure_limitations_db.csv](concept/azure_limitations_db.csv) — decides three
things the plan was going to have to guess at.

1. **Exact-match on `service` is not sufficient, but the fix is cheap.** There are only
   **14 distinct `service` values**, all human prose (`"Azure Blob Storage (SFTP)"`,
   `"Azure Site Recovery (Scout 8.0.1)"`). The primary persona — an AI agent about to
   emit IaC — will say `"AKS"`, `"blob storage"`, or `"Microsoft.Web/sites"`. None of
   those equal any stored value. A case-insensitive substring match over
   `service + feature + details + quote` is the minimum viable strategy; a curated alias
   map is the higher-fidelity option. **No index exists for either**, but at 93 rows a
   sequential scan is microseconds — the `< 800 ms p95` NFR does **not** constrain this
   choice. Pick the matching strategy on correctness grounds alone.

2. **Region/SKU scoping (FR-009, and the "optionally scoped by region / SKU" clause of
   FR-016) is not implementable on this data.** `region` is populated in **1 of 93 rows**
   — and that single value is a slash-delimited list of six regions, not a region code.
   `sku_tier` is populated in 14 rows with free-text values (`"Flex Consumption / Consumption"`).
   `condition` is populated in **0 rows**. Any region/SKU filter would silently discard
   ~99% of the corpus. This empirically confirms the PRD's demotion of FR-009 and means
   FR-016's optional scoping must be specified as *narrowing metadata attached to the
   response*, not as a `WHERE` clause.

3. **The three-value verdict is a genuine design decision, not a lookup.** The DB stores
   **8 distinct `support_status` values** per record; the PRD promises **3** per query.
   Ten of the fourteen services return a *mixed* status set — Azure Firewall alone yields
   `not_supported=12, known_issue=4, supported=1, partially_supported=1`. So the verdict
   requires (a) an 8→3 value mapping and (b) an aggregation policy across the matched set.
   Neither exists anywhere in the codebase or the PRD. This is the single largest
   unspecified decision in S-01.

Everything else is well-paved: the auth gate, the response-serialization conventions,
the migration style, and the test fixtures are all established and reusable.

## Detailed Findings

### 1. Seeded dataset — actual shape (primary focus)

Profiled directly from [concept/azure_limitations_db.csv](concept/azure_limitations_db.csv)
at commit `2ae625e`. 93 rows, 20 columns.

#### Field fill rates

| Field | Filled | Notes |
|---|---|---|
| `id`, `service`, `feature`, `support_status`, `limitation_type`, `details`, `source_type`, `source_url`, `source_title`, `quote`, `confidence`, `first_seen`, `last_seen` | **93/93 (100%)** | Every provenance field is populated — Risk #1's guardrail is satisfiable at the data layer |
| `workaround` | 49/93 (52%) | Optional in responses |
| `sku_tier` | **14/93 (15%)** | Free-text, not normalized |
| `environment` | 5/93 (5%) | Single value: `'on-premises / Arc'` |
| `auth_mode` | 2/93 (2%) | `'Local users only'`, `'SystemAssigned only'` |
| `network_mode` | 2/93 (2%) | `'outbound'` ×2 |
| `region` | **1/93 (1%)** | See below |
| `condition` | **0/93 (0%)** | Entirely empty |

The one populated `region` value is:

```
'East US 2 EUAP / North Europe / South Central US / Spain Central / West US 2 / Qatar Central'
```

— a slash-delimited human list, not an Azure region code. `sku_tier` is the same shape:
`'Flex Consumption / Consumption'`, `'Free Trial / Students'`, `'Enterprise Agreement'`.

**Consequence for the plan**: there is no normalized facet to filter on. `region = 'westeurope'`
matches nothing. Even `region ILIKE '%west us 2%'` matches exactly one row. FR-009 must stay
parked (as the PRD and roadmap already have it), and FR-016's *"optionally scoped by region /
SKU"* must be re-specified — the honest v1 behaviour is to accept the parameters, echo them
back as query context, and **not** use them to exclude records, because excluding on a 1%-filled
column is indistinguishable from a broken query.

#### `service` cardinality and naming

14 distinct values across 93 rows:

| n | service |
|---|---|
| 18 | Azure Firewall |
| 12 | Azure Kubernetes Service |
| 11 | Azure Blob Storage (SFTP) |
| 11 | Azure Resource Manager |
| 9 | Azure Functions |
| 7 | Azure Resource Groups |
| 5 | Azure Subscriptions |
| 5 | Azure Local |
| 4 | Azure Site Recovery (Scout 8.0.1) |
| 4 | Azure Container Apps |
| 3 | Azure Management Groups |
| 2 | Azure Container Registry |
| 1 | ARM Templates |
| 1 | Azure Networking |

Note `"Azure Blob Storage (SFTP)"` and `"Azure Site Recovery (Scout 8.0.1)"` — parenthetical
qualifiers baked into the identity column. And `"ARM Templates"` vs `"Azure Resource Manager"`
are two separate services for one concept.

**Consequence for the plan**: `WHERE service = :q` is a near-useless contract for the primary
persona. The plan must choose between, at minimum:

- **(a) case-insensitive substring** — `service ILIKE '%' || :q || '%'`. Handles `"firewall"`,
  `"blob storage"`. Fails `"AKS"`.
- **(b) substring across a wider column set** — `service`, `feature`, `details`, `quote`.
  Handles `"AKS"` only if the acronym appears in prose (it does, in some `details`/`quote`
  values). Risk: `quote` matching produces low-precision hits.
- **(c) curated alias map** — a small static dict (`aks → Azure Kubernetes Service`,
  `blob → Azure Blob Storage (SFTP)`) applied before (a). 14 services means this is a
  ~30-line constant, not an ingestion problem. Highest precision for the cost.

`feature` is **93 distinct values across 93 rows** — it is a per-record description
(`'Management groups per Microsoft Entra tenant'`, `'Tag key length'`), *not* a facet. It is
useful as match surface, useless as a filter dimension.

#### Category / status vocabularies

`support_status` — 8 values, validated at import by
[seed.py](seed.py) `SUPPORTED_VALUES`:

| n | support_status |
|---|---|
| 36 | not_supported |
| 27 | supported |
| 22 | known_issue |
| 2 | partially_supported |
| 2 | preview |
| 2 | deprecated |
| 1 | retired |
| 1 | support_ticket_required |

`limitation_type` — 18 values, long tail: `quota_limit=27`, `behavior=16`, `feature_gap=10`,
`error_code=10`, `operation_restriction=8`, then 13 values with ≤3 rows each. Viable as a
secondary filter facet (unlike region/SKU) since it is 100% populated.

`confidence` — `high=87`, `medium=6`. `source_type` — `learn_docs=48`,
`learn_troubleshoot=34`, `github_repo_issue=6`, `github_docs_repo=5`.

#### The verdict-aggregation problem

The PRD promises **supported / unsupported / constrained**
([context/foundation/prd.md](context/foundation/prd.md) §Business Logic, FR-016). The data
carries 8 statuses, and per-service mixes are the norm, not the exception:

| n | service | support_status mix |
|---|---|---|
| 18 | Azure Firewall | not_supported=12, known_issue=4, supported=1, partially_supported=1 |
| 12 | Azure Kubernetes Service | supported=6, not_supported=4, known_issue=2 |
| 11 | Azure Blob Storage (SFTP) | not_supported=8, supported=1, known_issue=1, preview=1 |
| 11 | Azure Resource Manager | known_issue=10, partially_supported=1 |
| 9 | Azure Functions | not_supported=4, supported=3, retired=1, preview=1 |
| 7 | Azure Resource Groups | supported=7 |
| 5 | Azure Subscriptions | supported=5 |
| 5 | Azure Local | known_issue=3, not_supported=2 |
| 4 | Azure Site Recovery (Scout 8.0.1) | deprecated=2, not_supported=2 |
| 4 | Azure Container Apps | known_issue=2, not_supported=2 |
| 3 | Azure Management Groups | supported=3 |
| 2 | Azure Container Registry | not_supported=1, support_ticket_required=1 |
| 1 | ARM Templates | supported=1 |
| 1 | Azure Networking | not_supported=1 |

Only 4 of 14 services are status-homogeneous. The plan must specify two rules the codebase
does not currently contain anywhere:

1. **8→3 mapping.** A defensible starting point: `not_supported`, `retired` → *unsupported*;
   `supported` → *supported*; `known_issue`, `partially_supported`, `preview`, `deprecated`,
   `support_ticket_required` → *constrained*. This is a product decision, not a technical one.
2. **Aggregation across the matched set.** "Azure Kubernetes Service" yields 12 records with
   three different statuses — one verdict must come out. A severity-precedence rule
   (`unsupported > constrained > supported`) is the conservative choice and matches the
   product's purpose (warn the agent before it commits). The alternative — majority vote —
   would report Azure Firewall as *unsupported* and AKS as *supported*, which is arguably
   worse for a go/no-go decision.

Note the semantic trap: a `supported` record in this corpus is usually a **quota limit**
(`limitation_type=quota_limit`, 27 rows), e.g. `'Management groups per Microsoft Entra
tenant: 10,000'`. "Supported, with a ceiling" is not the same as "no limitation" — the
verdict must not be read as an all-clear.

#### Freshness fields

`first_seen` and `last_seen` are **`2026-06-05` for all 93 rows** — zero variance.
`verification_state` is written as the literal `"verified"` for every row at import, and
`verified_at` is set to the import timestamp ([seed.py](seed.py), the `limitation_values`
block). So the NFR *"stale records are identifiable: each record's verification state and
age are observable to the consumer"* is satisfiable only by surfacing the fields — there is
no actual staleness signal in v1 data. Surface them; do not build logic on them.

### 2. Persistence layer — what the query can lean on

From [migrations/versions/20260729_01_create_sources_and_limitations.py](migrations/versions/20260729_01_create_sources_and_limitations.py):

- Indexes on `limitations`: **`ix_limitations_service`** (`service`) and
  **`ix_limitations_verification_state`** (`verification_state`). That is all.
- **No GIN/tsvector, no `pg_trgm`, no `LOWER()` expression index, no `CREATE EXTENSION`
  anywhere.** `ILIKE '%…%'` and any multi-column text search are sequential scans.
- Check constraints `ck_limitations_quote_not_blank` and `ck_limitations_confidence_not_blank`
  already enforce non-blank `quote`/`confidence` at the DB level — a real assist for Risk #1.
- `sources` is 1:N to `limitations` via `source_id` FK; `sources.url` is unique. Provenance
  (`source_url`, `source_title`) requires a join — see [models.py](models.py) `Limitation.source`
  relationship. Use `joinedload` (the pattern already used in [tests/test_seed_import.py](tests/test_seed_import.py))
  or the N+1 shows up on every response.

At 93 rows the sequential-scan cost is irrelevant. **Do not add a FTS index or extension for
v1** — it would be premature, and it would be the first `CREATE EXTENSION` in a project whose
deploy story is "forward-only migrations on managed Neon Postgres".

From [database.py](database.py):

- `DATABASE_URL` is **required, no fallback**; non-Postgres backends are rejected outright,
  and `postgresql://` is rewritten to `postgresql+psycopg://`.
- Sessions are **synchronous** (`sessionmaker`, `expire_on_commit=False`, `pool_pre_ping=True`).
  The new route must be `def`, not `async def` — matching every existing route in
  [main.py](main.py).

### 3. Auth gate — reuse, do not rebuild

[auth.py](auth.py) already provides the complete contract:

- `get_current_user` — parses `Authorization: Bearer …`, hashes with `hash_token`, looks up
  `Token`, checks `expires_at`, resolves `User`. **401** on every failure path.
- `require_active_license` — depends on `get_current_user`, checks for an `is_active` `License`.
  **403** on failure. Evaluated **per request**, not cached (FR-006).

[main.py](main.py) `/auth/probe` is the reference protected route and exists precisely as the
minimal example to copy:

```python
@app.get("/auth/probe")
def auth_probe(user: User = Depends(require_active_license)):  # noqa: B008
```

One `Depends(require_active_license)` transitively enforces both gates. Note the `# noqa: B008`
— ruff's default rules flag `Depends()` in defaults, and the house convention is the inline
suppression, applied consistently across [main.py](main.py) and [auth.py](auth.py).

Caveat: [auth.py](auth.py) defines its **own** `SessionFactory` and `get_db`, separate from the
one in [main.py](main.py). Two engines exist in-process today. The new endpoint should take
`db: Session = Depends(get_db)` from whichever module it lives in; the plan should decide
whether to consolidate or leave the duplication alone (leaving it alone is defensible — it is
pre-existing and out of S-01's scope).

### 4. Response serialization — the gap

**There are no Pydantic response models anywhere in the codebase.** Every route in
[main.py](main.py) returns a raw `dict`. That is fine for `{"status": "ok"}` but it is exactly
the thing test-plan Risk #1 warns about:

> "A typed Pydantic response model guarantees the fields are present" — presence ≠ populated;
> an empty string or null still types
> — [context/foundation/test-plan.md](context/foundation/test-plan.md) §Risk Response Guidance

So S-01 introduces the project's first response schema, and the guardrail test must assert
**non-empty values**, not just key presence — and must derive the expected values from the DB
row, not from the serializer under test (the oracle problem, named explicitly in the same table).

Established error conventions to match:

- `HTTPException(status_code=…, detail="<static string>")` — static details only, no
  interpolation of request data (20 existing raises follow this).
- Unhandled errors → `{"detail": "Internal Server Error"}` via the `@app.exception_handler(Exception)`
  handler in [main.py](main.py).
- **Empty match must be `200` with an empty list**, never 404/500 — Risk #6 and US-01's
  acceptance criterion.

Routing style: all routes are registered directly on `app` in [main.py](main.py); no `APIRouter`
modules exist yet. [main.py](main.py) is already ~330 lines. Whether the query core lands in a
new module (e.g. `query.py` + a router) or inline is an open plan decision — a separate module
is more consistent with [auth.py](auth.py)'s precedent of extracting a concern once it has real
logic.

### 5. Testing — fixtures exist, one is missing

From [tests/conftest.py](tests/conftest.py):

- Tests require a real **`TEST_DATABASE_URL`** Postgres; there is no SQLite path. Alembic is
  run to `head` on a session-scoped engine.
- Isolation is `TRUNCATE tokens, licenses, users, limitations, sources` per test via
  `clean_test_database`, not transactional rollback.
- Ready-made auth fixtures: `seeded_user`, `seeded_token` (returns `(raw, Token)`),
  `seeded_user_no_eula`, `seeded_user_no_license`, `seeded_user_inactive_license`.
- Env vars are `setdefault`-ed **before** importing `main`, which fails fast at module level.
- `TestClient(app, base_url="http://localhost")` — the base_url matters because
  `TrustedHostMiddleware` is active.

[tests/test_auth_probe.py](tests/test_auth_probe.py) is the template for 200/401/403 coverage.
[tests/test_seed_import.py](tests/test_seed_import.py) shows the limitation-seeding path
(`import_seed(SEED_CSV, session)`).

**What is missing**: a fixture that seeds a *deliberately unverified* limitation row. Every row
`import_seed` writes is `verification_state="verified"`, so a query that forgets its
`verification_state == 'verified'` filter would pass every existing test. test-plan names this
as the Risk #2 anti-pattern verbatim: *"Seeding only verified rows, so the test can never
observe a leak."* S-01's test suite must insert an unverified row by hand.

### 6. Quality gates that will fire

- **Per-edit agent hook**: [.github/hooks/lint-after-edit.json](.github/hooks/lint-after-edit.json)
  runs `uv run ruff check .` on `PostToolUse` (whole codebase, 15s timeout).
- **Pre-commit** ([lefthook.yml](lefthook.yml)): `uv run ruff check -- {staged_files}` and
  `uv run mypy -- {staged_files}`, parallel, `*.py` only. No pre-push hook. No CI
  (`.github/workflows/` does not exist — test-plan Phase 5, `not started`).
- **test-plan Phase 3** — *"Query-core provenance & support-status contract"*, covering Risks
  #1/#2/#6, status `not started`, no change folder yet. S-01 is the implementation slice; Phase 3
  is its test slice. The plan should decide whether to fold Phase 3's integration tests into S-01
  or open a separate testing change (the roadmap and test-plan currently treat them as separate
  tracks).

## Code References

- `concept/azure_limitations_db.csv` — 93 curated rows; the entire v1 corpus. **Gitignored.**
- `seed.py:17` — `MINIMUM_RECORD_COUNT = 93`
- `seed.py:28-64` — `SUPPORTED_VALUES`: the authoritative 8 `support_status`, 18 `limitation_type`,
  4 `source_type`, 2 `confidence` vocabularies
- `seed.py` (`limitation_values` block) — writes `verification_state="verified"` and
  `verified_at=imported_at` for every row; upsert on `id`, preserving `imported_at`
- `models.py:32-65` — `Limitation` model, incl. `verification_state`/`verified_at` and the
  `source` relationship
- `models.py:35-37` — `ck_limitations_quote_not_blank`, `ck_limitations_confidence_not_blank`
- `migrations/versions/20260729_01_create_sources_and_limitations.py:59-64` —
  `ix_limitations_service`, `ix_limitations_verification_state` (the only two indexes)
- `auth.py:36-63` — `get_current_user` (401 paths)
- `auth.py:66-80` — `require_active_license` (403 path)
- `main.py` (`/auth/probe`) — reference protected route, single `Depends(require_active_license)`
- `main.py` (`unhandled_exception_handler`) — `{"detail": "Internal Server Error"}` 500 contract
- `database.py:11-34` — Postgres-only URL validation, sync `sessionmaker`
- `tests/conftest.py` — `clean_test_database`, `seeded_user`, `seeded_token`, and the
  no-eula / no-license / inactive-license variants
- `tests/test_auth_probe.py` — 200/401/403 template for a protected route
- `tests/test_seed_import.py` — `joinedload(Limitation.source)` provenance-assertion pattern
- `lefthook.yml` — pre-commit ruff + mypy on staged files
- `.github/hooks/lint-after-edit.json` — PostToolUse `ruff check .`

## Architecture Insights

1. **`Depends()` for auth, ASGI middleware for infrastructure.** Established in F-03's frame
   and honoured throughout: host validation and request logging are middleware; token/license
   checks are dependencies. S-01 adds nothing new here.
2. **Middleware ordering is load-bearing.** Last-added runs outermost;
   `RequestLoggingMiddleware` is added after `TrustedHostMiddleware` deliberately so
   host-rejected 400s are still logged. A new route changes nothing, but do not reorder.
3. **Static error details, always.** No request data interpolated into `HTTPException.detail`.
   The `DatabaseConfigurationError` precedent (never echo the URL) is the house rule.
4. **Forward-only migrations.** Per [context/deployment/deploy-plan.md](context/deployment/deploy-plan.md)
   §7, schema changes do not roll back with code. S-01 arguably needs **no migration at all** —
   which is the cheapest possible answer to the index question.
5. **Zero-new-packages posture.** [context/foundation/tech-stack.md](context/foundation/tech-stack.md);
   F-03 promoted only `httpx`, which was already transitive. Pydantic is already available via
   FastAPI, so response models cost nothing.
6. **Migrate-before-serve on deploy**: `uv run alembic upgrade head && uv run uvicorn main:app …`
   is the Railway start command.

## Historical Context (from prior changes)

- [context/archive/2026-07-29-postgres-schema-seed/plan.md](context/archive/2026-07-29-postgres-schema-seed/plan.md)
  — "What We're NOT Doing" explicitly parks *query implementation, support-status classifier
  logic, and full-text/vector search* for S-01. Its Phase 1 contract states the migration
  "adds indexes for the future verified filter and service lookup" — i.e. the two existing
  indexes were placed **for this slice**, on the assumption of an exact `service` lookup plus a
  `verification_state` filter. This research shows the `service` half of that assumption is
  weaker than it looked.
- [context/archive/2026-07-29-auth-scaffold-token-license/frame.md](context/archive/2026-07-29-auth-scaffold-token-license/frame.md)
  — the two-chained-`Depends()` split and the 401/403 mapping; `/auth/probe` exists specifically
  as the minimal protected surface to copy.
- [context/archive/2026-08-02-observability-logging-floor/plan.md](context/archive/2026-08-02-observability-logging-floor/plan.md)
  — Phase 2 recorded that a `BaseHTTPMiddleware` cannot observe all statuses; handled
  `HTTPException`s are produced by the inner `ExceptionMiddleware`. Relevant if S-01 ever wants
  per-query logging: attach it to the route, not to new middleware.
- [context/changes/testing-auth-license-gate/research.md](context/changes/testing-auth-license-gate/research.md)
  — confirms per-request (uncached) license validation as the test oracle for Risk #3.
- [context/foundation/test-plan.md](context/foundation/test-plan.md) §2 — Risk #1 (provenance-less
  result), #2 (unverified record served), #6 (empty match returns an error) are all S-01's risks,
  with named anti-patterns for each.

## Related Research

- [context/archive/2026-07-29-auth-scaffold-token-license/research.md](context/archive/2026-07-29-auth-scaffold-token-license/research.md)
- [context/archive/2026-08-02-observability-logging-floor/research.md](context/archive/2026-08-02-observability-logging-floor/research.md)
- [context/changes/testing-auth-license-gate/research.md](context/changes/testing-auth-license-gate/research.md)

## Open Questions

1. **Matching strategy — the decision this research was opened to inform.** Exact `service`
   match is insufficient for the primary persona (14 prose-named services vs. agent shorthand
   like "AKS"). Options: ILIKE substring on `service`; ILIKE across `service`/`feature`/`details`/`quote`;
   or a ~14-entry curated alias map feeding an ILIKE. Performance is a non-issue at 93 rows.
   **Owner: user. Block: yes — the plan cannot specify the endpoint contract without it.**
2. **8→3 support-status mapping.** Which of the 8 stored statuses map to *supported*,
   *unsupported*, *constrained*? Proposed: `supported`→supported; `not_supported`,`retired`→unsupported;
   `known_issue`,`partially_supported`,`preview`,`deprecated`,`support_ticket_required`→constrained.
   **Owner: user. Block: yes.**
3. **Verdict aggregation across a mixed result set.** 10 of 14 services return mixed statuses.
   Proposed: severity precedence (`unsupported > constrained > supported`), which is conservative
   and matches the product's warn-before-commit purpose. **Owner: user. Block: yes.**
4. **FR-016's "optionally scoped by region / SKU".** `region` is 1% populated and `sku_tier` 15%,
   both free-text. Filtering on them would drop ~99% of the corpus. Recommend: accept the params,
   echo them in the response as query context, do not filter. **Owner: user. Block: no — but the
   PRD text should be annotated so the gap is not read as a defect.**
5. **Where the query core lives.** New module + `APIRouter`, or inline in the already-330-line
   [main.py](main.py)? [auth.py](auth.py) sets the precedent for extraction. **Owner: user. Block: no.**
6. **S-01 vs test-plan Phase 3.** Phase 3 ("Query-core provenance & support-status contract",
   Risks #1/#2/#6) is `not started` with no change folder. Fold its integration tests into S-01,
   or open a separate testing change afterwards? **Owner: user. Block: no.**
7. **The seed CSV is gitignored.** [.gitignore](.gitignore) excludes `concept/` (and `context/`,
   `.github/`). But [tests/test_seed_import.py](tests/test_seed_import.py) reads
   `concept/azure_limitations_db.csv`, so that test cannot run on a fresh clone or in CI. Not
   S-01's problem to fix, but it blocks test-plan Phase 5 (CI wiring) and is worth recording.
   **Owner: user. Block: no.**
8. **Duplicate `SessionFactory` / `get_db`.** Defined independently in [main.py](main.py) and
   [auth.py](auth.py), creating two engines in-process. Pre-existing; consolidation is out of
   S-01's scope unless the plan chooses otherwise. **Owner: user. Block: no.**
