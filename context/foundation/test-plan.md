# Test Plan

> Phased test rollout for this project. Strategy is frozen at the top
> (§1–§5); cookbook patterns at the bottom (§6) fill in as phases ship.
> Read before writing any new test.
>
> Refresh: re-run `/10x-test-plan --refresh` when stale (see §8).
>
> Last updated: 2026-08-26

## 1. Strategy

Tests follow three non-negotiable principles for this project:

1. **Cost × signal.** The cheapest test that gives a real signal for the
   risk wins. Do not promote to e2e because e2e "feels safer." Do not put a
   vision model on top of a deterministic assertion that already catches the
   regression.
2. **User concerns are first-class evidence.** Risks anchored in "the team
   is worried about X, and the failure would surface somewhere in <area>"
   carry the same weight as PRD lines or hot-spot data.
3. **Risks are scenarios, not code locations.** This plan documents *what
   could fail* and *why we believe it's likely* — drawn from documents,
   interview, and codebase *signal* (structure, test base). It does NOT
   claim to know which line owns the failure. That knowledge is produced by
   `/10x-research` during each rollout phase. If the plan and research
   disagree about where the failure lives, research is the ground truth.

Hot-spot scope used for likelihood weighting: none — only 2 commits in the
last 30 days (insufficient git history). Likelihood ratings rely on the PRD,
roadmap, and the Phase 2 interview instead of churn.

## 2. Risk Map

The top failure scenarios this project must protect against, ordered by
risk = impact × likelihood. Risks are failure scenarios in user / business
terms, not test names. The Source column cites the *evidence that surfaced
this risk* — never a specific file as "where the failure lives" (that is
research's job, see §1 principle #3).

| # | Risk (failure scenario) | Impact | Likelihood | Source (evidence — not anchor) |
|---|-------------------------|--------|------------|--------------------------------|
| 1 | API returns a limitation record missing source URL / quote / confidence — a provenance-less result the agent trusts anyway | High | High | PRD §Guardrails, FR-010; interview Q1, Q4 |
| 2 | An unverified / unapproved record is served through the REST API or MCP tool | High | Medium | FR-012, FR-011; interview Q3 |
| 3 | An expired or missing token, or an inactive Demo license, still returns protected data | High | Medium | FR-006, PRD §Access Control + §Guardrails, US-01 AC |
| 4 | A token or secret value leaks into a log line or error response body | High | Medium | PRD §Guardrails + NFR (no secrets in logs), FR-004 |
| 5 | CSV → DB import silently drops or mangles rows, or loses verification metadata, thinning the dataset unnoticed | High | High | FR-011; interview Q3, Q2 |
| 6 | An empty match returns an error (404/500) instead of a clean empty result, so the agent reads the service as broken | Medium | Medium | US-01 AC; interview Q1 |
| 7 | The app reports healthy while misconfigured — allowed-hosts rejects real traffic, or readiness stays green while the DB is unreachable | High | Medium | interview Q2; infrastructure.md (health-check host); FR-013 |

**Impact × Likelihood rubric.** Both axes are coarse High / Medium / Low so
two readers agree on the same row. The goal is ordering, not false
precision.

| Rating | Impact | Likelihood |
|--------|--------|------------|
| High   | user loses access, data, or money; failure is publicly visible | area changes weekly, or we have already been burned here |
| Medium | feature degrades, a workaround exists, only some users affected | touched occasionally, has been a source of bugs |
| Low    | cosmetic, easily reverted, no data effect | stable code, rarely touched |

**Abuse / security lens.** AzLimits has auth and accepts user input, so the
map carries abuse scenarios directly: #3 covers authorization/access
(per-request token + license, not just authentication) and #4 covers
secret/PII leakage. Untrusted-input / injection was considered but not given
its own row: the query core is unbuilt, its search params are typed Pydantic
inputs, and parameterized DB access is expected — a standalone row would be
speculative today (§1 principle: no inventing code to break). It is folded
into the research context for #2 and #6 (verify server-side validation
parity and parameterized queries when S-01 is built). Rate-limit / abusive
volume (an NFR) was dropped as a test risk: no rate limiter exists in any v1
slice, so it belongs to observability / a future slice, not this rollout.

### Risk Response Guidance

| Risk | What would prove protection | Must challenge | Context `/10x-research` must ground | Likely cheapest layer | Anti-pattern to avoid |
|------|-----------------------------|----------------|--------------------------------------|-----------------------|-----------------------|
| #1 | Every record in a multi-record response carries a non-empty source URL + quote + confidence/verification state | "A typed Pydantic response model guarantees the fields are present" — presence ≠ populated; an empty string or null still types | The response serialization path and the independent source-of-truth for provenance fields | integration | Asserting one happy record; taking the expected value from the serializer under test (oracle problem) |
| #2 | A deliberately unverified DB row never appears in API/MCP results | "Import only loads verified rows, so the query needn't filter" | Where the verified/approved filter is applied — at import, at query, or both | integration | Seeding only verified rows, so the test can never observe a leak |
| #3 | Expired token → rejected; inactive license → rejected; valid + licensed → served; validated per request, not cached | "A valid token implies a valid license" — license state can change mid-token-life | The token+license validation entry point and whether license state is cached | integration | Happy-path-only: exercising only a valid, licensed token |
| #4 | A token/secret value never appears in emitted logs or error bodies, including on the error/exception path | "We don't log tokens" — tracebacks and error responses can echo request data | The secret-stripping middleware and the error-response path | unit + integration | Asserting only the success log; never exercising the failure path |
| #5 | Importing the fixture CSV yields the expected row count with every provenance field populated and verification metadata set; malformed/short rows are rejected loudly | "The import succeeded because it didn't throw" — a silent drop looks like success | The import/normalization function and the required-field + verification mapping | unit + integration | Asserting only a row count on a clean CSV |
| #6 | A no-match query returns HTTP 200 with an explicit empty result | "No rows means an error" | The query-core empty path and the endpoint's status-code mapping | integration | Asserting only the populated case |
| #7 | An unknown Host is rejected; the readiness endpoint reports unhealthy when the DB is unreachable | "Health 200 means the app works" — health is static; readiness must check dependencies | The allowed-hosts middleware and the readiness dependency check (arrives with F-02) | unit + integration | Testing only the healthy path |

## 3. Phased Rollout

Each row is a discrete rollout phase that will open its own change folder
via `/10x-new`. Status moves left-to-right through the values below; the
orchestrator updates Status as artifacts appear on disk.

| # | Phase name | Goal (one line) | Risks covered | Test types | Status | Change folder |
|---|------------|-----------------|---------------|------------|--------|---------------|
| 1 | Import & provenance integrity | Prove the seed import preserves every provenance field and never silently drops rows | #5, #2, #1 | unit + integration | change opened | context/changes/testing-import-provenance-integrity/ |
| 2 | Auth/license gate + secret stripping | Prove the per-request token+license gate rejects correctly and no secret leaks | #3, #4 | integration + unit | researched | context/changes/testing-auth-license-gate/ |
| 3 | Query-core provenance & support-status contract | Prove every served record carries provenance, unverified are excluded, and empty matches return a clean empty result | #1, #2, #6 | integration | complete | context/changes/rest-search-query-core/ |
| 4 | Deploy-config & readiness safety | Prove "healthy" cannot lie: host rejection plus readiness reflecting DB state | #7 | unit + integration | not started | — |
| 5 | Quality-gates wiring | Lock lint/typecheck and pytest in CI | cross-cutting | gates | complete | context/changes/deploy-pipeline/ |

**Status vocabulary** (fixed — parser literals): `not started` →
`change opened` → `researched` → `planned` → `implementing` → `complete`.

## 4. Stack

The classic test base for this project. AI-native tools (if any) carry a
`checked:` date so future readers can see which lines need re-verification.

| Layer | Tool | Version | Notes |
|-------|------|---------|-------|
| unit + integration | pytest | >=8.0 | Configured in `pyproject.toml` (`[tool.pytest.ini_options]`, `pythonpath=["."]`) |
| API / HTTP client | httpx + FastAPI `TestClient` | >=0.27 | Already used by `tests/test_health.py`; in-process, no running server |
| DB fixtures | pytest + disposable PostgreSQL | PostgreSQL 16 in CI | `tests/conftest.py` applies migrations and isolates `TEST_DATABASE_URL`; CI provisions a service container |
| lint + typecheck | Ruff + mypy | locked dev dependencies | Required locally and in the reusable GitHub Actions quality workflow |
| e2e | not planned for v1 | — | API + MCP only, no UI (PRD §Non-Goals); integration covers the surface |
| AI-native | none — deterministic typed contracts, no UI | n/a | When NOT to use: never add a vision/LLM-judge layer over a deterministic JSON contract an assertion already catches. Revisit if relevance-matching becomes fuzzy (v1.1, Open Question #4) |

**Stack grounding tools (current session):**
- Docs: Microsoft Learn MCP — available; relevant to Azure *content*, not to the pytest/FastAPI test stack, so not used for tooling choices; checked: 2026-07-26
- Search: none — no Exa.ai / web-search MCP available in current session; checked: 2026-07-26
- Runtime/browser: Playwright / browser tools — available but low value (product is API + MCP only, no UI); not used; checked: 2026-07-26
- Provider/platform: GitHub PR + git MCP — available; relevant to §3 Phase 5 CI quality-gate wiring; checked: 2026-07-26

## 5. Quality Gates

The full set of gates that must pass before a change reaches production.
"Required after §3 Phase N" means the gate is enforced once that rollout
phase lands; before that, the gate is `planned`.

| Gate | Where | Required? | Catches |
|------|-------|-----------|---------|
| lint + typecheck | local + CI | required | syntactic / type drift |
| unit + integration | local + CI | required after §3 Phase 1 | logic regressions, provenance/import defects |
| provenance guardrail (no result without source URL + quote) | CI on PR | required after §3 Phase 3 | provenance-less results (Risk #1) |
| auth/license gate + secret-stripping | CI on PR | required after §3 Phase 2 | access bypass (Risk #3), secret leakage (Risk #4) |
| readiness reflects dependencies | CI on PR | required after §3 Phase 4 | false-healthy deploys (Risk #7) |
| exact-SHA release smoke (`/version` then `/health` over HTTPS) | after Railway deploy | required for a successful release | stale revision and environment-specific liveness failures |

## 6. Cookbook Patterns

How to add new tests in this project. Each sub-section is filled in once the
relevant rollout phase ships; before that, the sub-section reads "TBD — see
§3 Phase N."

### 6.1 Adding a unit test

- **Location**: `tests/`, next to related tests (reference: `tests/test_health.py`).
- **Naming**: `test_<unit>.py`.
- **Reference test**: `tests/test_health.py`.
- **Run locally**: `uv run pytest tests/ -v`.

### 6.2 Adding an integration test (DB-backed)

- Set `TEST_DATABASE_URL` to an isolated PostgreSQL database; never point it at
   the operator or Railway `DATABASE_URL`.
- Request `clean_test_database` in the test signature. It applies Alembic
   migrations once per test session and truncates `limitations` and `sources`
   before each database case.
- Run: `uv run pytest tests/test_seed_import.py -v`.
- The fixture passes its connection directly to Alembic, so tests do not read
   or fall back to `DATABASE_URL`.

### 6.3 Adding a test for the import / normalization path

- Reference: `tests/test_seed_import.py`.
- Compare imported limitation counts with `read_seed_records` from the committed
   CSV, and compare source counts with the CSV's distinct source URLs.
- Assert every limitation retains source URL/title, quote, confidence, verified
   state, and a non-null verification timestamp.
- Re-run the import and assert source and limitation counts remain unchanged.
- Create a malformed fixture with a missing required provenance field and assert
   `SeedValidationError` plus unchanged persisted counts.

### 6.4 Adding a test for the auth/license gate

- Use a context-managed `TestClient`, `seeded_token`, and a per-test in-memory
   handler attached directly to the non-propagating application loggers.
- Restore logger levels and disabled state in fixture teardown because Alembic's
   test setup can disable existing application loggers.
- Assert `RAW_TOKEN` is absent from every captured record on both valid-token
   and authentication-error paths.
- Add a temporary raising route for 500 coverage; remove it in teardown and
   assert its traceback and clean response body contain no raw token.

### 6.5 Adding a test for a new API endpoint (query core)

- Seed rows through the ORM rather than `import_seed`, then independently load the persisted
   rows with `joinedload(Limitation.source)` for provenance expectations.
- Assert non-empty source URL, source title, quote, confidence, and verification state on
   **every** response record, cross-checking each field against the independently loaded DB row.
- Include an explicitly `unverified` row whenever testing a verified-filtered query, and assert
   it is absent from both the returned records and the support-status verdict.
- Assert the no-match path returns HTTP 200 with an empty record list and a `supported` verdict.

### 6.6 Per-rollout-phase notes

(Optional. After each phase lands, `/10x-implement` appends a 2–3 line note
here capturing anything surprising the rollout phase taught.)

## 7. What We Deliberately Don't Test

Exclusions agreed during the rollout (Phase 2 interview, Q5). Future
contributors should respect these unless the underlying assumption changes.

- **GitHub's OAuth provider itself** — do not test GitHub's flow; test only our callback handling, EULA gate, and license assignment. Re-evaluate if a second identity provider is added (PRD Open Question #1). (Source: Phase 2 interview Q5.)
- **Railway provider internals** — do not reproduce Railway's own build/deploy
  engine in unit tests. Repository workflow contracts, Railway JSON parsing,
  deployment correlation, exact-SHA verification, bounded failure behavior,
  and evidence normalization are deterministic tests; hosted target selection,
  native-autodeploy state, canaries, and rollback remain manual checks.
- **FastAPI / Pydantic framework internals** (serialization, OpenAPI generation) — the framework is the test; assert *our* contract fields are populated, not that serialization works. Re-evaluate never, unless a custom serializer is introduced.
- **AI-native / vision review** — no UI exists (API + MCP only); deterministic typed contracts make a vision/LLM-judge layer pure cost. Re-evaluate if relevance-matching becomes non-deterministic (v1.1).

## 8. Freshness Ledger

- Strategy (§1–§5) last reviewed: 2026-08-26
- Stack versions last verified: 2026-07-26
- AI-native tool references last verified: 2026-07-26

Refresh (`/10x-test-plan --refresh`) when:

- a new top-3 risk surfaces from the roadmap or archive,
- a recommended tool's `checked:` date is older than three months,
- the project's tech stack changes (new framework, new test runner),
- §7 negative-space no longer matches what the team believes.
