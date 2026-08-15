<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: REST Search Endpoint — Query Core + Provenance + Support-Status Verdict

- **Plan**: context/changes/rest-search-query-core/plan.md
- **Scope**: All phases (1–3 of 3)
- **Date**: 2026-08-05
- **Verdict**: APPROVED
- **Findings**: 0 critical, 2 warnings, 3 observations
- **Triage**: all 5 findings FIXED on 2026-08-05; full suite (48 tests) + ruff + mypy green after fixes

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | WARNING |
| Success Criteria | PASS |

## Findings

### F1 — LIKE wildcards not escaped in substring fallback

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: main.py:400
- **Detail**: If `q` contains `%` or `_`, they act as LIKE wildcards in the `ilike` fallback (e.g. `q="_"` matches every non-null feature; `q="%"` matches everything). Gated by the verified filter and a 93-row curated corpus, so a correctness foot-gun, not an exploit — but the route semantics are "substring match", so wildcard interpretation is a behavioral surprise.
- **Fix**: Escape `%`, `_`, and the escape char in `q` (`q.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")`) and pass `escape="\\"` to `ilike`.
- **Decision**: FIXED — escaped wildcards + `escape="\\"` on both ilike predicates; 7 search tests pass, ruff/mypy clean.

### F2 — pydantic imported directly but not declared in pyproject.toml

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: pyproject.toml (dependencies); schemas.py:3
- **Detail**: schemas.py imports pydantic directly, but pydantic only arrives transitively via fastapi. If fastapi's dependency spec ever changes, the import breaks without a manifest signal.
- **Fix**: Add `pydantic>=2` to `dependencies` in pyproject.toml.
- **Decision**: FIXED — declared in pyproject.toml, lockfile refreshed, pydantic 2.13.4 resolves.

### F3 — Unbounded result set on search query

- **Severity**: 🔵 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: main.py:405
- **Detail**: No `LIMIT` on the query. Acceptable at ~93 rows, but the cap is only the corpus size — an implicit invariant that will silently weaken as ingestion grows.
- **Fix**: Add a defensive `.limit(500)` with a comment, or record the corpus-size invariant in the change doc.
- **Decision**: FIXED — `.limit(500)` with corpus-invariant comment at main.py.

### F4 — No max_length on query params; no ORDER BY

- **Severity**: 🔵 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: main.py:385-390, 405
- **Detail**: `q` has `min_length=1` but no `max_length`; `region`/`sku` unbounded — a multi-MB `q` flows into the LIKE pattern. Also, result order is undefined (no `ORDER BY`), making response order unstable across requests.
- **Fix**: Add `max_length` (e.g. 200) to the three query params and `ORDER BY service, id` for deterministic output.
- **Decision**: FIXED — max_length=200 on q/region/sku; `order_by(service, id)` before the limit.

### F5 — No-token smoke test lacks clean-database fixture

- **Severity**: 🔵 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: tests/test_limitations_search.py:34
- **Detail**: `test_search_requires_a_token` requests no `clean_test_database`/`auth_db_session` fixture. It passes today because 401 fires before any DB access, but every sibling test requests the clean-DB fixture — the inconsistency is a latent fragility if auth ever touches the DB earlier.
- **Fix**: Add `clean_test_database` to the test signature for symmetry.
- **Decision**: FIXED — fixture added; full suite (48 tests) green, ruff/mypy clean.
