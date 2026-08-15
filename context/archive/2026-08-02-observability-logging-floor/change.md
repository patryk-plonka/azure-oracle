---
change_id: observability-logging-floor
roadmap_id: F-04
title: Observability floor + secrets-stripped logging
status: archived
created: 2026-08-02
updated: 2026-08-03
archived_at: 2026-08-03T11:21:23Z
owner: user
prd_refs: NFR (minimal logging floor), FR-013, FR-014 (Parked)
roadmap_refs: F-04
---

# Change: Observability floor + secrets-stripped logging

Foundation F-04 — request + error logging middleware with secrets stripped from
logs and error bodies. The minimal logging floor the PRD NFR requires; full
structured/correlated logging (FR-014) is Parked, not in scope here.

## Artifacts

- `research.md` — codebase + conventions research (this change)
- `plan.md` — implementation plan (to be produced by `/10x-plan`)
