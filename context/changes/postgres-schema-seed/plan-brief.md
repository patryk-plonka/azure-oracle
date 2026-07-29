# Postgres Schema and Verified Seed Import — Plan Brief

> Full plan: `context/changes/postgres-schema-seed/plan.md`
> Frame brief: `context/changes/postgres-schema-seed/frame.md`

## What & Why

AzLimits needs a reliable Postgres foundation that turns its curated CSV into
safe query data. The plan defines and enforces a CSV-to-query-data contract that
preserves required provenance, records curation-derived verification, and rejects
incomplete or undersized v1 imports.

## Starting Point

The FastAPI service currently exposes only `/health`; no database schema,
migrations, importer, or DB-backed tests exist. The committed CSV is
provenance-complete but has 93 rows, so the plan rebaselines the v1 requirement
from `>=100` to `>=93` rather than hiding that mismatch.

## Desired End State

An operator can migrate an external Neon/Postgres database and explicitly seed
it from the committed CSV. Each limitation retains its quote, confidence,
freshness, and verification state; shared source identity is normalized; reruns
are atomic and idempotent. Focused integration tests run against a separate
PostgreSQL database and prove that malformed or undersized input cannot corrupt
the dataset.

## Key Decisions Made

| Decision | Choice | Why | Source |
| --- | --- | --- | --- |
| Persistence | SQLAlchemy 2, Alembic, psycopg | Provides typed models and forward-only schema evolution for subsequent foundations. | Plan |
| Provenance model | Normalized `sources` plus limitation-specific provenance fields | Avoids duplicated source identity without losing per-record quotes or confidence. | Plan |
| Dataset threshold | `>=93` verified records | Matches the reviewed current CSV and preserves a minimum without an artificial exact count. | Plan |
| Import behavior | Transactional PostgreSQL upsert | Makes repeat seeds safe and guarantees malformed input leaves no partial data. | Plan |
| DB test strategy | Dedicated `TEST_DATABASE_URL` | Exercises real PostgreSQL without ever falling back to production credentials. | Plan |

## Scope

**In scope:**

- Versioned Postgres schema for sources and limitations
- Strict CSV validation, verification stamping, and operator-only seed command
- 93-record threshold synchronization in the PRD, roadmap, and frame
- PostgreSQL-backed migration and seed regression tests
- Railway migration handoff and database-test documentation

**Out of scope:**

- Query endpoint, auth tables, live ingestion, review UI, and automatic reseeding
- Destructive production reloads or migration rollback automation

## Architecture / Approach

The CSV remains version-controlled input. Alembic creates `sources` and
`limitations`; the importer validates the whole CSV, upserts source URLs and
limitation IDs in one transaction, and records import-derived verification.
Railway receives only `DATABASE_URL`; `TEST_DATABASE_URL` remains isolated for
local and CI database tests.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Contract and Schema | Aligned 93-record requirement, dependencies, models, migration | A schema that cannot preserve the later query contract |
| 2. Seed Import | Strict, atomic, idempotent CSV-to-Postgres command | Partial, duplicate, or provenance-poor seed data |
| 3. Verification | Dedicated Postgres tests and operational cookbook | A test setup that touches production or misses real DB behavior |

**Prerequisites:** An externally managed Neon/Postgres instance for operator validation, plus a separate disposable PostgreSQL database for `TEST_DATABASE_URL`.
**Estimated effort:** ~2-3 sessions across 3 phases.

## Open Risks & Assumptions

- The 93-row threshold is an intentional product rebaseline; expanding coverage later must still preserve the same validation contract.
- Railway startup migration is suitable for the single-instance MVP; later multi-replica deployment should move migration execution to a dedicated release job.
- The seed command remains a human-approved operation because production import is a data-changing action.

## Success Criteria (Summary)

- Migrations produce a Postgres schema that enforces source uniqueness, limitation identity, and verified provenance fields.
- The committed 93-row CSV imports atomically, reruns without duplicates, and rejects malformed or undersized files before writes.
- A separate PostgreSQL test database proves row-count parity, provenance retention, verification metadata, and rollback behavior.