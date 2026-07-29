# Frame Brief: Postgres schema seed

> Framing step before /10x-plan. This document captures what is *actually*
> at issue, separated from what was initially assumed.

## Reported Observation

The product needs a Neon Postgres foundation with a limitations/sources schema
and a curated CSV import of at least 93 verified records.

## Initial Framing (preserved)

- **User's stated cause or approach**: This is one change, `postgres-schema-seed`
- **User's proposed direction**: Wire the external database, create the schema, and seed verified source-backed data
- **Pre-dispatch narrowing**: Database contract

## Dimension Map

The observation could originate at any of these dimensions:

1. **Row-to-schema mapping** -- the flat CSV may not map cleanly to the intended limitations + sources model
2. **Import-time verification semantics** -- curation-derived verification and serving eligibility may not be recorded or enforceable
3. **Query/result compatibility** -- the stored model may not guarantee every result's provenance and verification fields

## Hypothesis Investigation

| Hypothesis | Evidence | Verdict |
| --- | --- | --- |
| Row-to-schema mapping is unresolved | Roadmap F-02 explicitly asks whether the CSV aligns with the limitations + sources schema; source fields repeat in the flat CSV | STRONG |
| Verification semantics are absent from the input contract | PRD FR-011/FR-012 require verified-only serving; the CSV has confidence and dates but no explicit verification field | STRONG |
| The data model is not yet aligned to served-result guarantees | PRD FR-010 and the test plan require populated provenance and verification state; no database schema or importer exists | STRONG |

## Narrowing Signals

- The CSV is a beta dataset: existing columns may be used and additional columns may be added for v1.
- Curation itself is the current authority that every imported row is verified.
- The committed CSV contains 93 data rows, satisfying the v1 minimum of 93 verified records.

## Cross-System Convention

The project test strategy treats import integrity as a product boundary: it must
prove row count, populated provenance, retained verification metadata, and loud
rejection of malformed input. This matches the PRD guardrails that no served
record lacks provenance or verification state.

## Reframed (or Confirmed) Problem Statement

> **The actual problem to plan around is**: Define and enforce a curated-CSV-to-query-data contract that preserves required provenance, records curation-derived verification, and rejects incomplete or undersized v1 imports.

The original scope was directionally correct, but a database connection and
tables alone would not establish the product guarantee. The planning boundary
must start from the fields and invariants that a later query can safely serve,
while allowing the beta CSV to grow beyond its current 93 records.

## Confidence

- **HIGH** -- direct PRD and test-plan requirements, a measured row-count gap,
  and the user's clarification all point to the same contract boundary.

## What Changes for /10x-plan

Plan the data foundation as an enforceable import and serving contract, not as
schema wiring alone. The plan must resolve the flat-input versus sources-model
ambiguity and state the v1 completeness and verification invariants.

## References

- Source files: `context/foundation/prd.md` (FR-010, FR-011, FR-012), `context/foundation/roadmap.md` (F-02), `context/foundation/test-plan.md` (risks 1, 2, and 5), `concept/azure_limitations_db.csv`
- Related research: none
- Investigation tasks: CSV schema mapping, verification semantics, retrieval contract, independent data-foundation check