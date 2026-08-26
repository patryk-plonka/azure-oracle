# Verifiable Railway Releases from Main — Plan Brief

> Full plan: `context/changes/deploy-pipeline/plan.md`
> Frame brief: `context/changes/deploy-pipeline/frame.md`
> Research: `context/changes/deploy-pipeline/research.md`

## What & Why

Production has no observable, machine-verifiable release chain tying a specific `main` Git SHA to that SHA's quality result, its Railway deployment, the running application's reported SHA, and a contemporaneous `/health` 200 result. This plan adds that complete chain and automatically releases every successfully checked update to `main`.

## Starting Point

Railway can already build and run the application, apply Alembic migrations, and gate activation on `/health`. Ruff, mypy, and PostgreSQL-backed coverage run for limited PR events, but no deploy workflow, runtime SHA endpoint, or exact-SHA release evidence joins those pieces.

## Desired End State

Every merge or direct push to `main` starts one serialized release. The triggering SHA passes reusable quality checks, is embedded in the uploaded Railway source, is reported by `/version`, and is verified alongside `/health`; the run retains a safe summary and JSON evidence artifact.

## Key Decisions Made

| Decision | Choice | Why | Source |
| --- | --- | --- | --- |
| Problem boundary | End-to-end exact-SHA release evidence | A deploy trigger alone cannot prove what is running | Frame |
| Trigger | `push` restricted to `main` | Covers merges and direct pushes without duplicate events | Research |
| Deployment control | GitHub Actions-controlled Railway CLI | Keeps the release contract reviewable in the repository | Research |
| Local missing SHA | Report `unknown`; production verifier rejects it | Preserves local ergonomics without weakening hosted acceptance | Plan |
| Production approval | Fully automatic after exact-SHA checks | Matches auto-deploy-on-main intent | Plan |
| PR freshness | Add `synchronize` | Provides current feedback while still rechecking final `main` SHA | Plan |
| Release evidence | Actions summary plus retained JSON artifact | Auditable without broader GitHub deployment permissions | Plan |
| Failure recovery | Visible failure and human rollback | Code rollback cannot reverse forward-only migrations | Plan |
| Health boundary | `/health` remains process liveness | Dependency readiness belongs to a separate test-plan change | Frame |

## Scope

**In scope:**

- Public cache-resistant `/version` with full Git SHA or local `unknown`.
- Generated release metadata inside the Railway upload bundle.
- Reusable exact-SHA Ruff, mypy, and PostgreSQL/coverage checks.
- Fresh PR checks on `synchronize`.
- Serialized automatic Railway deployment for `main` pushes.
- Scoped production token, explicit targets, pinned Railway CLI 5.30.1.
- Machine-readable deployment correlation, bounded `/version` and `/health` verification.
- Safe run summary, retained evidence artifact, workflow tests, operator handoff, and rollback drill.

**Out of scope:**

- Database readiness, `/ready`, staging, previews, canaries, multi-region, or HA.
- Railway native branch autodeploy alongside GitHub Actions.
- Automatic rollback or database down migrations.
- GitHub Deployment API records and application runtime secrets in Actions.

## Architecture / Approach

`push: main` invokes the reusable quality workflow for the triggering SHA. After all jobs pass, one non-canceling production job generates `release.json`, deploys that source using pinned Railway CLI JSON mode, correlates the Railway deployment ID/status, then verifies the public `/version` SHA and `/health` 200. A deterministic worker writes normalized evidence to the job summary and retained artifact; only Railway CLI steps receive the scoped token.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Runtime Release Identity | Strict generated SHA metadata and public `/version` | Local fallback accidentally accepted in production |
| 2. Reusable Exact-SHA Quality Gate | One canonical workflow for PR and release checks | Trigger or checkout semantics validate the wrong SHA |
| 3. Serialized Railway Release Pipeline | Automatic deploy, correlation, smoke verification, evidence | Duplicate/canceled migration-capable deployments or secret leakage |
| 4. Production Enablement and Handoff | Correct docs, configured control plane, canary and rollback evidence | Dashboard configuration diverges from repository contract |

**Prerequisites:** GitHub Actions enabled; a `production` Environment; Railway project/environment/service identifiers and HTTPS public URL; a project-scoped Railway token; Railway native `main` autodeploy disabled before enablement.

**Estimated effort:** Approximately 4 focused implementation sessions plus hosted canary and rollback verification.

## Open Risks & Assumptions

- Railway CLI 5.30.1 JSON output and deployment-list behavior must be validated before the pin is enabled in production.
- The public hostname must be present in `ALLOWED_HOSTS`, or external verification receives 400 while Railway's internal activation check may pass.
- `/health` proves liveness only; database readiness remains intentionally unresolved outside this change.
- A release may apply a forward-only migration before later verification fails, so rollback compatibility remains a human judgment.
- Artifact retention follows repository/organization policy and must be long enough for the intended audit window.

## Success Criteria (Summary)

- Every `main` push produces at most one serialized Railway deployment only after canonical checks pass for that exact SHA.
- Successful evidence records one matching source, quality, Railway deployment, runtime, and liveness chain with no timestamp inference.
- Failure, stale revision, mismatch, timeout, and unhealthy paths stop visibly, retain safe evidence, expose no secrets, and require deliberate human rollback.
