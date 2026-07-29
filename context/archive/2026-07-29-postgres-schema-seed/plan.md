# Postgres Schema and Verified Seed Import Implementation Plan

## Overview

Create the first persistent data foundation for AzLimits: a Neon Postgres schema,
forward-only migrations, and a validated curated-CSV importer. The importer must
normalize reusable source identity, preserve every limitation's provenance and
verification state, and safely upsert the committed 93-record v1 dataset.

## Current State Analysis

The app has only a FastAPI health endpoint in `main.py`; no database driver,
models, migration tooling, importer, or database fixtures exist. The committed
CSV is the source of truth and contains 93 provenance-complete rows, but the
upstream documents still promise at least 100. The frame brief established that
the real boundary is a safe CSV-to-query-data contract, not table creation.

## Desired End State

An operator can run committed Alembic migrations against the externally managed
Postgres database and invoke a local/operator-only seed command using
`DATABASE_URL`. It atomically validates and imports the 93-row CSV, records all
rows as verified by the curated import, deduplicates sources, and can be run
again without duplicates. A separate `TEST_DATABASE_URL` proves the migration
and import contract against PostgreSQL.

### Key Discoveries:

- The CSV has 20 fields and 93 data rows, with source URL, title, quote,
  confidence, and dates on each row (`concept/azure_limitations_db.csv`).
- FR-010 and the test plan require every served record to retain populated
  provenance and verification state (`context/foundation/prd.md`,
  `context/foundation/test-plan.md`).
- Railway uses external managed Neon Postgres via `DATABASE_URL`; migrations are
  forward-only and imports against production remain human-gated
  (`context/deployment/deploy-plan.md`).

## What We're NOT Doing

- No REST search endpoint, support-status classifier, or query implementation.
- No OAuth, users, tokens, licenses, or authorization tables; those belong to
  `auth-scaffold-token-license`.
- No review UI, live/scheduled ingestion, source crawler, or automatic data
  refresh.
- No automatic seed on application startup or every Railway deploy.
- No production migration rollback or destructive truncation/reload workflow.

## Implementation Approach

Use synchronous SQLAlchemy 2 with psycopg and Alembic because this small
FastAPI service has no async database surface yet, while versioned migrations
provide the required safe path to later auth and query schemas. Model source
identity once by canonical URL in `sources`; store limitation-specific quote,
confidence, observation dates, and import-derived verification fields in
`limitations`. A CLI/module entry point validates the entire CSV before a single
transactional PostgreSQL upsert. `DATABASE_URL` is only for deployed/local
operator data; tests require an isolated `TEST_DATABASE_URL`.

## Critical Implementation Details

Validate every CSV row and the minimum record count before issuing writes. Keep
the import in one transaction so malformed input rolls back all source and
limitation changes; the operator runs migrations before application startup, but
seeding remains a deliberate human-approved command.

## Phase 1: Rebaseline Contract and Create the Database Foundation

### Overview

Synchronize the chosen 93-record MVP commitment across planning artifacts, then
add the versioned Postgres access and schema foundation.

### Changes Required:

#### 1. MVP data-contract documents

**Files**: `context/foundation/prd.md`, `context/foundation/roadmap.md`, `context/changes/postgres-schema-seed/frame.md`

**Intent**: Replace the unsatisfied `>=100 verified records` promise with the
approved `>=93 verified records` v1 threshold, while retaining the stronger
provenance, verification, and rejection requirements.

**Contract**: FR-011, F-02, and the frame must agree that the committed CSV's
93 verified rows satisfy v1; future growth remains allowed and no exact-count
constraint is introduced.

#### 2. Postgres dependencies and configuration

**Files**: `pyproject.toml`, `uv.lock`, `database.py`

**Intent**: Add SQLAlchemy 2, Alembic, and psycopg, plus a small database module
that creates engines/sessions from the required connection URL without logging
the URL or its credentials.

**Contract**: Runtime database access reads `DATABASE_URL`; test wiring can pass
an explicit `TEST_DATABASE_URL` without falling back to production. Missing or
malformed URLs fail with a redacted configuration error.

#### 3. ORM models and initial migration

**Files**: `models.py`, `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/<revision>_create_sources_and_limitations.py`

**Intent**: Establish a single migration-managed schema suitable for later
verified-only querying and preserve all relevant CSV fields.

**Contract**: `sources` has a stable primary key and unique source URL with its
title/type. `limitations` has CSV ID as a stable unique identifier, FK to a
source, all limitation-specific CSV attributes, non-empty quote/confidence,
and import-derived verification state/timestamp. The migration adds indexes for
the future verified filter and service lookup; it never creates auth tables.

### Success Criteria:

#### Automated Verification:

- Dependencies resolve and lockfile updates: `uv sync --all-groups`
- Initial migration applies to the isolated database: `uv run alembic upgrade head`
- ORM metadata and generated migration agree without pending schema changes
- Lint and typecheck pass for database modules: `uv run ruff check database.py models.py migrations` and `uv run mypy database.py models.py`

#### Manual Verification:

- A human provisions an isolated Neon/Postgres database and sets `DATABASE_URL` outside source control
- A human confirms the updated PRD/roadmap/frame consistently state the `>=93` v1 threshold

**Implementation Note**: After the automated checks pass, pause for the human
to confirm database provisioning and the product-contract change before moving
to seed implementation.

---

## Phase 2: Implement the Validated Idempotent Seed Import

### Overview

Turn the committed CSV into the only v1 seed input and import it safely through
strict validation, normalized source resolution, and transactional upserts.

### Changes Required:

#### 1. Seed import service and operator command

**Files**: `seed.py`, `concept/azure_limitations_db.csv`

**Intent**: Parse the CSV, validate required fields and supported values,
normalize source identity, stamp curation-derived verification metadata, and
upsert sources plus limitations as one repeatable import operation.

**Contract**: The command accepts an explicit CSV path and uses `DATABASE_URL`.
It rejects duplicate IDs, missing/blank required provenance fields, malformed
dates, unsupported enum values, or fewer than 93 rows before committing. It
uses PostgreSQL conflict updates keyed by source URL and limitation ID, returns
only non-sensitive counts, and leaves existing data unchanged if any validation
or write fails.

#### 2. Railway migration handoff and operator instructions

**Files**: `railway.json`, `context/deployment/deploy-plan.md`

**Intent**: Make schema migration part of the deploy startup handoff while
documenting seeding as a separate human-approved operation.

**Contract**: The process applies `alembic upgrade head` before Uvicorn starts.
The deploy plan documents the ordered production procedure: provision Neon,
set `DATABASE_URL`, migrate, then run the seed command; it does not add a
production `TEST_DATABASE_URL` variable or auto-run a destructive import.

### Success Criteria:

#### Automated Verification:

- Seed command imports the committed CSV into an empty isolated database
- Re-running the same seed command leaves source and limitation counts unchanged
- The command rejects a fixture with a missing required field and leaves the database unchanged
- The command rejects an input below 93 records before issuing writes

#### Manual Verification:

- A human executes the documented migration then seed sequence against the intended Neon environment
- A human inspects the reported counts and confirms no connection string or credentials appear in output

**Implementation Note**: After the automated checks pass, pause for human
confirmation of the non-destructive Neon seed run before proceeding to the
test and operations handoff.

---

## Phase 3: Prove Import Integrity and Document the Test Pattern

### Overview

Build the PostgreSQL-backed regression coverage that protects the import boundary
and replace the test-plan placeholders with the resulting cookbook pattern.

### Changes Required:

#### 1. Dedicated PostgreSQL test fixtures

**Files**: `tests/conftest.py`, `tests/test_seed_import.py`

**Intent**: Isolate database tests from production and verify the migration plus
the real importer against a disposable database named by `TEST_DATABASE_URL`.

**Contract**: Tests run migrations for the test database, clean only that
database between cases, and never use `DATABASE_URL`. They assert CSV-to-table
row-count parity, retained provenance, non-null verification state, source
deduplication, idempotent re-import, and complete transaction rollback when a
malformed row is supplied.

#### 2. Test and operator documentation

**Files**: `context/foundation/test-plan.md`, `README.md`

**Intent**: Record the canonical database-test setup and the operator commands
needed to migrate, seed, and validate a local or CI environment.

**Contract**: The test plan's DB-backed/import cookbook sections name
`TEST_DATABASE_URL`, the fixture lifecycle, and Risk #5's row/provenance/
verification/malformed-row assertions. README instructions distinguish test,
operator, and Railway production connection variables without publishing any
values.

### Success Criteria:

#### Automated Verification:

- Database import tests pass against `TEST_DATABASE_URL`: `uv run pytest tests/test_seed_import.py -v`
- Full suite passes: `uv run pytest tests/ -v`
- Lint and typecheck pass: `uv run ruff check .` and `uv run mypy .`
- Migration can be recreated from an empty isolated test database and seeded successfully

#### Manual Verification:

- A human verifies the test database is distinct from the production Neon database before running the suite
- A human reviews the revised test-plan cookbook and operational README commands for clarity

**Implementation Note**: After automated verification, pause for the human to
confirm environment isolation and operational documentation before marking this
foundation complete.

## Testing Strategy

### Unit Tests:

- CSV parser rejects blank `id`, `service`, `source_url`, `source_title`,
  `quote`, `confidence`, or invalid date/value fields with the row identifier.
- The minimum 93-row contract fails before any database write.
- Source normalization chooses one source record per canonical source URL.

### Integration Tests:

- Alembic creates the schema in the dedicated PostgreSQL test database.
- Import row count equals CSV row count and every imported limitation carries a
  non-empty URL, title, quote, confidence, and verification metadata.
- A second import updates in place without duplicate sources or limitations.
- A malformed CSV rolls back the entire transaction rather than leaving a
  partial seed.

### Manual Testing Steps:

1. Provision the managed Neon database and set `DATABASE_URL` only in the
   operator/Railway environment.
2. Apply the migration, run the seed command once, and record its safe counts.
3. Run the same command again and confirm unchanged counts.
4. Set a separate `TEST_DATABASE_URL`, run the focused test file, then confirm
   the production database was not contacted.

## Performance Considerations

The seed is small (93 rows), so correctness and atomicity take priority over
bulk-load optimization. Indexing `limitations.service` and verified state keeps
the later low-QPS query core within the PRD response budget without committing
to full-text search in this foundation.

## Migration Notes

Migrations are forward-only. Test them against the isolated database before the
human applies them to Neon. A failed seed rolls back its transaction; schema
changes are repaired by a new migration, never by editing or deleting a deployed
migration. The CSV remains in version control as the re-seed artifact.

## References

- Frame brief: `context/changes/postgres-schema-seed/frame.md`
- Product requirements: `context/foundation/prd.md` (FR-010 through FR-012)
- Roadmap foundation: `context/foundation/roadmap.md` (F-02)
- Import-risk strategy: `context/foundation/test-plan.md` (Risks #1, #2, #5)
- Deployment guardrails: `context/deployment/deploy-plan.md`
- Seed source: `concept/azure_limitations_db.csv`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Rebaseline Contract and Create the Database Foundation

#### Automated

- [x] 1.1 Dependencies resolve and lockfile updates — b709ae4
- [x] 1.2 Initial migration applies to the isolated database — b709ae4
- [x] 1.3 ORM metadata and generated migration agree without pending schema changes — b709ae4
- [x] 1.4 Lint and typecheck pass for database modules — b709ae4

#### Manual

- [x] 1.5 Isolated Neon/Postgres database provisioned and DATABASE_URL set outside source control — b709ae4
- [x] 1.6 PRD, roadmap, and frame consistently state the >=93 v1 threshold — b709ae4

### Phase 2: Implement the Validated Idempotent Seed Import

#### Automated

- [x] 2.1 Seed command imports the committed CSV into an empty isolated database
- [x] 2.2 Re-running the seed command leaves source and limitation counts unchanged
- [x] 2.3 Seed command rejects a malformed fixture without database changes
- [x] 2.4 Seed command rejects an input below 93 records before issuing writes

#### Manual

- [x] 2.5 Documented migration and seed sequence succeeds against the intended Neon environment
- [x] 2.6 Seed output contains no connection string or credentials

### Phase 3: Prove Import Integrity and Document the Test Pattern

#### Automated

- [x] 3.1 Database import tests pass against TEST_DATABASE_URL
- [x] 3.2 Full test suite passes
- [x] 3.3 Lint and typecheck pass
- [x] 3.4 Migration recreates an empty isolated test database that seeds successfully

#### Manual

- [x] 3.5 Test database isolation from production has been verified
- [x] 3.6 Test-plan cookbook and README operator instructions have been reviewed