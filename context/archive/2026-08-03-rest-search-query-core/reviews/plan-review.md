<!-- PLAN-REVIEW-REPORT -->
# Plan Review: REST Search Endpoint — Query Core + Provenance + Support-Status Verdict

- **Plan**: context/changes/rest-search-query-core/plan.md
- **Mode**: Deep
- **Date**: 2026-08-05
- **Verdict**: REVISE → SOUND (after fixes)
- **Findings**: 0 critical, 3 warnings, 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding

8/8 paths ✓, 4/4 symbols ✓, brief↔plan ✓. Codebase verification: shared-engine ✓, ORM-seedability ✓, no name collisions ✓, truncation isolation ✓, pydantic v2.13.4 (transitive via FastAPI).

## Findings

### F1 — Pydantic v2 syntax not pinned in the plan

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1, change 2 (Response schemas)
- **Detail**: The plan introduces the project's first Pydantic models but never states the version. Pydantic is transitive-only (via fastapi>=0.139.2) and resolves to v2.13.4 in uv.lock. An implementer writing v1-style `class Config` or `.dict()` produces code that fails or misbehaves.
- **Fix**: Add one line to Phase 1 change 2 — "Pydantic v2 (locked 2.13.4 via FastAPI): use `model_config = ConfigDict(...)` and `model_dump()`, never inner `class Config` or `.dict()`."
- **Decision**: FIXED (Fix in plan)

### F2 — Which `get_db` the route uses is unspecified

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2, change 1 (Search route)
- **Detail**: Two identical `get_db` functions exist — main.py:103 and auth.py:25 — each backed by its own engine. The plan says `db: Session = Depends(get_db)` without saying which. Both work, but the implementer has to guess, and picking auth.py's couples the route to the auth module for no reason.
- **Fix**: State explicitly in Phase 2 change 1 — "use main.py's own `get_db` (the route lives in main.py); do not import auth.py's."
- **Decision**: FIXED (Fix in plan)

### F3 — TestClient Host header requirement not carried into the plan

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 2 change 2 + Phase 3 (all integration tests)
- **Detail**: TrustedHostMiddleware allows only localhost,127.0.0.1,healthcheck.railway.app. TestClient's default Host is `testserver`, rejected with 400. Existing tests pass `base_url="http://localhost"` for exactly this reason. The plan's test contracts never mention it — an implementer writing `TestClient(app)` bare gets a 400 on every call with no plan guidance on why.
- **Fix**: Add to Phase 2 change 2 — "construct TestClient as `TestClient(app, base_url="http://localhost")` (TrustedHostMiddleware rejects the default `testserver` host with 400)."
- **Decision**: FIXED (Fix in plan)

### F4 — Seeded test rows must satisfy the btrim check constraints

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 2 change 2 + Phase 3 (ORM seeding)
- **Detail**: Tests seed Limitation rows directly via the ORM. The DB enforces `btrim(quote) <> ''` and `btrim(confidence) <> ''` — a test seeding `quote=" "` fails at INSERT with an IntegrityError, not at the assertion the test was written to check.
- **Fix**: Note in Phase 2 change 2 — "seeded `quote`/`confidence` must be non-blank after trim (DB check constraints ck_limitations_*)."
- **Decision**: FIXED (Fix in plan)

### F5 — Global 500 handler hides tracebacks from failing search tests

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 2/3 (test debugging)
- **Detail**: main.py's global `@app.exception_handler(Exception)` converts any unhandled error into a flat `{"detail": "Internal Server Error"}`. A search route bug surfaces in tests as a bare 500 with no traceback in the response body — the implementer must read captured log output, not the response.
- **Fix**: One line in Phase 2 change 2 — "a 500 from the route surfaces as `{"detail": "Internal Server Error"}` (global handler); check the captured log for the real traceback."
- **Decision**: FIXED (Fix in plan)
