# Verifiable Railway Releases from Main Implementation Plan

## Overview

Create a repository-owned release pipeline that automatically deploys every successful update to `main` to Railway and proves that one Git SHA passed canonical quality checks, produced the Railway deployment, is reported by the running application, and returned a contemporaneous `/health` 200 result. The release remains fully automatic after exact-SHA checks pass; failed deployment or verification stops visibly for human rollback.

## Current State Analysis

The application is already deployable on Railway: `railway.json` runs Alembic before Uvicorn and uses `/health` as the activation check. The missing capability is an end-to-end release identity and evidence chain.

The existing deterministic workflow runs Ruff, mypy, and PostgreSQL-backed coverage only for pull requests opened or marked ready for review. It cannot be called by another workflow and does not establish fresh quality evidence for the final commit pushed to `main`. No production deployment workflow exists, Railway deployments are not correlated to a Git SHA, and the application exposes liveness but not its running source revision.

The frame established that dependency-aware readiness is a separate obligation. This change preserves `/health` as process liveness and does not introduce `/ready`.

## Desired End State

Every push to `main`, whether produced by a merge or a direct push, starts exactly one serialized release run. The run executes the repository's canonical quality jobs against the triggering full SHA, uploads that same source tree plus immutable release metadata to Railway using an exactly pinned CLI, waits for a terminal deployment result, and then verifies that the public application reports the same SHA through `/version` and returns HTTP 200 from `/health`.

Each successful run leaves a non-secret GitHub Actions summary and retained JSON evidence artifact containing the source SHA, quality run identity, Railway deployment ID and terminal status, observed runtime SHA, health result, and timestamps. A failed release does not auto-rollback a migration-capable deployment; it fails visibly and leaves recovery to the documented human rollback procedure.

### Key Discoveries

- `.github/workflows/pr-quality.yml:3-61` contains the canonical checks but currently has neither `workflow_call` nor `push` coverage.
- `tests/test_pr_workflows.py:47-111` already treats workflow structure, immutable actions, secret profiles, and `.gitignore` allowlisting as tested repository contracts.
- `railway.json:3-5` applies forward-only migrations before Uvicorn and defines `/health` as Railway's activation check; deployments must be serialized and must not be canceled mid-flight.
- `main.py:188-190` and `tests/test_health.py:6-12` define a static liveness contract that must remain unchanged.
- `main.py:55-70` loads required runtime settings at import time, so release identity must retain a safe local fallback instead of making every local/test import supply a SHA.
- `.gitignore:27-34` ignores new GitHub assets unless their exact paths are allowlisted.
- Railway CLI 5.30.1 documents machine-readable `railway up --json` output, terminal-status exit codes, and JSON deployment listings; the implementation must validate and pin that exact version before production use.
- `context/deployment/deploy-plan.md:19-39,171-175`, `context/foundation/tech-stack.md:8-10,33-35`, and `context/foundation/test-plan.md:96-112,198-205` contain stale manual-deploy, Fly.io, or pre-CI handoff statements.

## What We're NOT Doing

- No dependency-aware `/ready` endpoint or database-readiness acceptance gate.
- No pull-request preview environments, staging environment, canary traffic split, multi-region deployment, or high-availability design.
- No Railway native GitHub branch autodeploy alongside the Actions-controlled pipeline.
- No automatic rollback, down migration, destructive data operation, or claim that code rollback reverses Alembic migrations.
- No application runtime secrets in GitHub Actions; `DATABASE_URL`, OAuth credentials, token hash salt, application tokens, and provider credentials remain in Railway or their existing secret stores.
- No GitHub Deployment API integration or `deployments: write` permission; release evidence lives in the Actions run summary and retained artifact.
- No deployment on pull-request events. A merged pull request is covered by the resulting `push` to `main`.

## Implementation Approach

Build the evidence chain in dependency order. First, add a minimal public runtime identity contract backed by a generated release metadata file, while retaining `unknown` for local execution and rejecting it in hosted verification. Next, turn the existing quality workflow into the single reusable source of deterministic checks and refresh PR feedback on `synchronize`. Then add the serialized production workflow and a testable verification worker that records safe evidence. Finally, update operational handoffs and enable the workflow only after a human confirms Railway and GitHub production configuration.

## Critical Implementation Details

### Release metadata lifecycle

The deploy workflow must materialize a small release metadata file in the Railway upload context before `railway up`; the file contains the triggering full 40-character lowercase Git SHA and no secrets. Railway CLI uploads the current directory while respecting `.gitignore`, so the metadata path must be intentionally included and covered by tests. Local source trees without this generated file report `unknown`; production smoke verification treats `unknown`, malformed, abbreviated, or mismatched values as failure.

### Deployment correlation

Use Railway CLI 5.30.1 in attached, machine-readable mode. Parse the terminal result from `railway up --json`, require a successful terminal status and deployment identifier, and cross-check the newest service deployment through `railway deployment list --json` without relying on timestamp correlation alone. Do not retain raw build logs as the release artifact; retain only the safe normalized evidence fields.

### Deployment sequencing

Use one fixed production concurrency group with cancellation disabled. The Railway token exists only on Railway CLI steps; the post-deploy verifier receives only the expected SHA, public HTTPS URL, and safe deployment metadata. The verifier must check `/version` before `/health` with bounded retries and per-request/overall timeouts so an old but healthy revision cannot satisfy acceptance.

## Phase 1: Runtime Release Identity

### Overview

Add an observable, cache-resistant source revision contract without changing liveness semantics or making local development depend on hosted release metadata.

### Changes Required:

#### 1. Release identity loader

**File**: `release_identity.py`

**Intent**: Centralize loading and validation of generated release metadata so the API and tests share one strict definition of a deployable Git SHA.

**Contract**: Read the generated root-level `release.json` metadata file, accept only one full 40-character lowercase hexadecimal `git_sha`, and return `unknown` when the file is absent in a local source tree. Treat present-but-malformed metadata as a configuration error rather than silently downgrading it to `unknown`.

#### 2. Generated deployment metadata contract

**File**: `release.json` (generated during the deployment workflow; absent from normal source control)

**Intent**: Carry the triggering Git identity inside the exact source bundle uploaded by `railway up`, avoiding persistent Railway variable mutation and provider-specific Git metadata that is absent for CLI uploads.

**Contract**: The upload bundle contains a JSON object with exactly `git_sha`, set to `${{ github.sha }}` as a full lowercase SHA. The deployment workflow creates it from a step environment value, not by interpolating GitHub expressions directly into shell source.

#### 3. Public version endpoint

**File**: `main.py`

**Intent**: Expose the running revision as a minimal unauthenticated operational endpoint next to `/health` so release automation can compare production with the triggering commit.

**Contract**: `GET /version` returns HTTP 200 and `{\"git_sha\": \"<full-sha-or-unknown>\"}` without database, token, or license dependencies. Add `Cache-Control: no-store`; do not expose repository, branch, deployment credentials, environment values, or other build metadata. Preserve `GET /health` and its response unchanged.

#### 4. Release identity tests

**File**: `tests/test_version.py`

**Intent**: Lock the metadata parser and public endpoint against false or stale release attestations.

**Contract**: Cover exact configured SHA reporting, absent-file `unknown`, malformed/abbreviated/extra-key metadata rejection, public access without DB/auth dependencies, the minimal response shape, and the no-store cache policy. Isolate metadata fixtures from the repository root and avoid import-order-dependent environment mutation.

### Success Criteria:

#### Automated Verification:

- Release identity tests pass: `uv run pytest tests/test_version.py tests/test_health.py -v`
- Static checks pass: `uv run ruff check release_identity.py main.py tests/test_version.py tests/test_health.py`
- Type checks pass: `uv run mypy release_identity.py main.py tests/test_version.py`
- Full repository tests and coverage pass against disposable PostgreSQL: `uv run pytest tests/ -v --cov --cov-branch --cov-report=term-missing`

#### Manual Verification:

- Starting the application from a normal local checkout makes `GET /version` return `unknown` with `Cache-Control: no-store`, while `GET /health` still returns its existing 200 response.
- Starting from a temporary upload context containing a valid `release.json` makes `/version` return that exact full SHA and exposes no additional runtime metadata.

**Implementation Note**: After completing this phase and all automated verification passes, pause for human confirmation of the two local endpoint checks before proceeding.

---

## Phase 2: Reusable Exact-SHA Quality Gate

### Overview

Make the existing deterministic checks callable from the release workflow and keep pull-request feedback current without duplicating the quality commands.

### Changes Required:

#### 1. Reusable quality workflow

**File**: `.github/workflows/pr-quality.yml`

**Intent**: Preserve one canonical Ruff, mypy, and PostgreSQL/coverage implementation for both pull requests and releases.

**Contract**: Add `workflow_call` and `synchronize` to the existing event contract while retaining `opened` and `ready_for_review`. Each job checks out the triggering SHA explicitly with persisted credentials disabled. Keep `contents: read`, immutable action references, pinned uv, isolated `TEST_DATABASE_URL`, and the existing commands/coverage floor; accept no secrets or caller inputs.

#### 2. Workflow contract tests

**File**: `tests/test_pr_workflows.py`

**Intent**: Update deterministic tests for the reusable trigger and explicit checkout identity before any secret-bearing deployment workflow depends on it.

**Contract**: Assert the exact PR plus `workflow_call` events, all three canonical jobs, triggering-SHA checkout with `persist-credentials: false`, read-only permissions, immutable actions, pinned uv/Python, disposable PostgreSQL, and absence of provider or production secrets.

### Success Criteria:

#### Automated Verification:

- Workflow contract tests pass: `uv run pytest tests/test_pr_workflows.py -v`
- YAML parses and exposes `pull_request` plus `workflow_call` with the approved event set.
- Static and type checks pass: `uv run ruff check .` and `uv run mypy .`
- Full repository tests and coverage pass against disposable PostgreSQL: `uv run pytest tests/ -v --cov --cov-branch --cov-report=term-missing`

#### Manual Verification:

- A same-repository test PR receives fresh Ruff, mypy, and PostgreSQL/coverage runs when a new commit is pushed after opening.

**Implementation Note**: Do not configure or expose the Railway token in this phase. Pause for human confirmation of the hosted PR synchronize run URL before proceeding; Phase 3 supplies the real reusable-workflow caller.

---

## Phase 3: Serialized Railway Release Pipeline

### Overview

Add the automatic `main` release workflow, machine-verifiable deployment correlation, bounded runtime acceptance, and safe retained evidence.

### Changes Required:

#### 1. Production deployment workflow

**File**: `.github/workflows/deploy-production.yml`

**Intent**: Automatically release exactly one production deployment for every successfully checked `main` push while keeping production credentials isolated to the deployment boundary.

**Contract**: Trigger only on `push.branches: [main]`; grant only `contents: read`; use fixed `railway-production` concurrency with `cancel-in-progress: false`. A `quality` job calls `./.github/workflows/pr-quality.yml`; a dependent `deploy` job uses the `production` GitHub Environment, checks out `${{ github.sha }}` with persisted credentials disabled, generates `release.json`, installs Railway CLI exactly at 5.30.1, and runs `railway up --json` with explicit project, environment, and service targets. Only the Railway CLI deployment/status steps receive `RAILWAY_TOKEN`. Do not use `--detach`, mutable versions, native branch autodeploy, runtime secrets, or implicit linked targets.

#### 2. Release verification and evidence worker

**File**: `verify_release.py`

**Intent**: Keep deployment-result parsing, exact-SHA runtime verification, bounded liveness checks, and safe evidence generation deterministic and unit-testable instead of embedding complex shell in YAML.

**Contract**: Consume only the expected full SHA, HTTPS application base URL, Railway JSON result/list data, and output path. Require a unique successful Railway deployment ID, then retry `/version` and `/health` within fixed per-request and overall budgets. Parse `/version` structurally and require exact full-string equality; reject `unknown`, malformed JSON, redirects outside the configured origin, non-HTTPS URLs, non-200 responses, and timeouts. Write a normalized JSON artifact containing safe identifiers, statuses, endpoint results, and UTC timestamps; append the same facts as a concise GitHub step summary. Never accept or log credentials, authorization headers, arbitrary response bodies, or raw Railway logs.

#### 3. Verification worker tests

**File**: `tests/test_verify_release.py`

**Intent**: Prove that hosted acceptance cannot be satisfied by an old healthy deployment, ambiguous Railway result, or unsafe endpoint behavior.

**Contract**: Cover success, runtime SHA mismatch, `unknown`, abbreviated/malformed SHA, malformed JSON, health failure, bounded transient retries, timeout exhaustion, redirected/cross-origin responses, non-HTTPS configuration, ambiguous/missing deployment IDs, failed Railway status, normalized evidence contents, and absence of secret-like input/output fields.

#### 4. Deployment workflow contract tests

**File**: `tests/test_pr_workflows.py`

**Intent**: Treat release triggers, permissions, sequencing, secret scope, exact targets, tool pinning, and evidence retention as reviewable code contracts.

**Contract**: Add the production workflow path and assertions for exact `push: main`, reusable-quality dependency, fixed non-canceling concurrency, `production` environment, immutable checkout, pinned Railway CLI 5.30.1, generated full-SHA metadata before upload, `railway up --json` without detach, explicit project/environment/service variables, deployment status correlation, verifier ordering, bounded `/version` then `/health` checks, step-scoped token, forbidden application/provider secrets, safe summary, and a retained evidence artifact uploaded by an action pinned to a full commit SHA.

#### 5. GitHub asset allowlist

**File**: `.gitignore`

**Intent**: Make the planned production workflow trackable while preserving the repository's narrow ignore policy for unrelated local `.github` material.

**Contract**: Add an exact negation for `.github/workflows/deploy-production.yml`; do not broaden the allowlist to arbitrary workflows or GitHub files.

### Success Criteria:

#### Automated Verification:

- Release verifier tests pass: `uv run pytest tests/test_verify_release.py -v`
- Workflow contract tests pass: `uv run pytest tests/test_pr_workflows.py -v`
- The production workflow is trackable: `git check-ignore --no-index .github/workflows/deploy-production.yml` returns nonzero.
- Static and type checks pass: `uv run ruff check .` and `uv run mypy .`
- Full repository tests and coverage pass against disposable PostgreSQL: `uv run pytest tests/ -v --cov --cov-branch --cov-report=term-missing`

#### Manual Verification:

- Review the workflow without enabling it and confirm the `production` environment is fully automatic, its token is project/environment scoped, target identifiers and public URL are non-secret variables, and no application runtime secret is present in GitHub.
- Confirm Railway native GitHub branch autodeploy for `main` is disabled before the Actions workflow can run.
- Run the verifier against controlled fixtures/endpoints and confirm SHA mismatch, stale healthy revision, health failure, timeout, and malformed response paths all fail with bounded, secret-free output.

**Implementation Note**: Do not merge or manually dispatch a secret-bearing production workflow until all automated checks and the three human configuration reviews pass.

---

## Phase 4: Production Enablement and Handoff

### Overview

Align operational documentation with the implemented release model, enable the production environment, and perform the first auditable release and rollback drill.

### Changes Required:

#### 1. Deployment runbook

**File**: `context/deployment/deploy-plan.md`

**Intent**: Replace the stale first/manual-deployment story with the current automatic exact-SHA release procedure and a concrete failure/rollback playbook.

**Contract**: Update frontmatter, current prerequisites, GitHub Environment configuration, Railway target variables, single-control-plane rule, release evidence fields, automatic trigger, health-versus-readiness boundary, failure triage, disabling procedure, and human rollback steps. State explicitly that rollback restores code/config only and database migrations remain forward-only. Remove obsolete claims that the app is a stub or CI/CD is still out of scope.

#### 2. Developer and operator documentation

**File**: `README.md`

**Intent**: Explain the public `/version` contract and how maintainers interpret a production release run without exposing sensitive configuration.

**Contract**: Document local `unknown` behavior, generated production SHA metadata, `/health` liveness semantics, required GitHub/Railway configuration names without values, evidence artifact contents, and the manual rollback entry point.

#### 3. Foundation handoff corrections

**Files**: `context/foundation/tech-stack.md`, `context/foundation/test-plan.md`, `context/foundation/roadmap.md`, `context/foundation/infrastructure.md`

**Intent**: Remove contradictions that would otherwise send future agents back to Fly.io, manual deployment, stale quality-gate status, or Railway native autodeploy.

**Contract**: Record Railway as the selected deployment target; mark deterministic quality wiring and release smoke plumbing as implemented when verified; keep dependency readiness explicitly pending; move/remove the parked auto-deploy follow-up; and describe Railway native autodeploy as an alternative that must remain disabled under the Actions-controlled design. Preserve dated historical research rather than rewriting it as if it were originally about this pipeline.

### Success Criteria:

#### Automated Verification:

- Documentation no longer presents Fly.io or manual CLI deployment as the current target: targeted `rg` checks find no active contradictory handoff statements.
- Workflow, verifier, static, type, and full PostgreSQL-backed test commands from Phase 3 still pass after documentation changes.
- `change.md` remains `status: planned` until implementation begins, and the plan retains exactly one canonical `## Progress` section.

#### Manual Verification:

- Merge or directly push a safe canary commit to `main` and record the pushed SHA, quality run URL, Railway deployment ID/status, `/version` reported SHA, `/health` status, verification timestamps, and retained evidence artifact URL; all SHA values must match exactly.
- Push a follow-up safe canary and confirm non-canceling serialization produces one deployment per push with no native Railway duplicate.
- Exercise a controlled failed verification and confirm the workflow fails visibly, retains safe evidence, does not expose secrets, and does not auto-rollback.
- Perform and record a human rollback drill to the prior deployment; confirm service liveness, document any forward-migration constraint, and verify deterministic quality workflows remain enabled.
- Review Actions and Railway logs for the canary, failure, and rollback runs and confirm no raw token, OAuth credential, database URL, hash salt, authorization header, or provider secret appears.

**Implementation Note**: This phase is complete only after the human records the non-secret evidence above. Do not infer success solely from a green workflow badge or timestamp correlation.

---

## Testing Strategy

### Unit Tests

- Validate release metadata parsing independently of FastAPI import order.
- Verify `/version` exact response shape, no-store behavior, local fallback, and malformed metadata failure.
- Exercise Railway JSON parsing, exact deployment selection, URL validation, bounded retry/timeout behavior, exact SHA comparison, health failure, and normalized evidence generation.
- Assert failure output cannot include secret-bearing inputs or raw provider responses.

### Integration Tests

- Parse all workflows and assert triggers, permissions, immutable references, job dependencies, concurrency, environment, target arguments, secret scope, release metadata ordering, smoke ordering, and artifact retention.
- Run the full test suite against disposable PostgreSQL so reusable quality behavior remains identical to the protected application contract.
- Use mocked HTTPS responses for the verifier's `/version` and `/health` sequence, including stale-but-healthy production behavior.

### Manual Testing Steps

1. Verify GitHub `production` Environment variables identify the intended Railway project, environment, service, and HTTPS public URL; verify only the scoped project token is secret.
2. Verify Railway native branch autodeploy is disabled and the service variables still contain all application runtime secrets without copying them to GitHub.
3. Validate PR `synchronize` feedback and capture the hosted run URL.
4. Release a safe canary through `main`, then compare the source SHA, quality run SHA, Railway deployment ID/status, `/version` SHA, and `/health` result in the retained evidence.
5. Release a second safe canary to prove serialization and exactly one deployment per push.
6. Trigger a controlled verification failure and confirm bounded failure, safe evidence, no automatic rollback, and no secret leakage.
7. Roll back manually to the prior Railway deployment, confirm `/health`, and record the forward-migration caveat.

## Performance Considerations

`/version` is a static metadata read and must not access PostgreSQL or external services. The implementation may load validated metadata once at process startup; the response must remain cache-resistant at HTTP intermediaries. Deployment verification uses bounded retries with short per-request timeouts and an overall deadline, adding only a finite post-deploy delay. Production releases are deliberately serialized because startup can execute migrations.

## Migration Notes

No database schema migration is introduced by this plan. Existing releases may execute forward-only Alembic migrations during startup, which is why deployment cancellation and automatic rollback remain disabled. Removing or disabling the production workflow stops future automated deployments but does not undo a deployed revision or schema change. A code rollback must be evaluated against the schema already applied in production.

## References

- Frame: `context/changes/deploy-pipeline/frame.md`
- Research: `context/changes/deploy-pipeline/research.md`
- Planning prior: `context/foundation/lessons.md`
- Current quality workflow: `.github/workflows/pr-quality.yml:3-61`
- Workflow tests: `tests/test_pr_workflows.py:47-111`
- Runtime liveness: `main.py:188-190`, `tests/test_health.py:6-12`
- Railway runtime contract: `railway.json:3-5`
- Deployment and rollback policy: `context/deployment/deploy-plan.md:128-156`
- Original Railway deployment: `context/archive/2026-07-20-deploy-skeleton-health/plan.md:137-146`
- Railway CLI deploy reference: `https://docs.railway.com/cli/up`
- Railway deployment reference: `https://docs.railway.com/cli/deployment`
- Railway CLI 5.30.1 release: `https://github.com/railwayapp/cli/releases/tag/v5.30.1`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Runtime Release Identity

#### Automated

- [x] 1.1 Release identity and liveness tests pass — 71e8ba0
- [x] 1.2 Release identity static checks pass — 71e8ba0
- [x] 1.3 Release identity type checks pass — 71e8ba0
- [x] 1.4 Full PostgreSQL-backed suite and coverage pass — 71e8ba0

#### Manual

- [x] 1.5 Local checkout reports `unknown` while preserving `/health` — 71e8ba0
- [x] 1.6 Valid generated metadata reports the exact full SHA without extra metadata — 71e8ba0

### Phase 2: Reusable Exact-SHA Quality Gate

#### Automated

- [x] 2.1 Reusable workflow contract tests pass — 0599065
- [x] 2.2 Workflow YAML exposes the approved PR and reusable events — 0599065
- [x] 2.3 Repository static and type checks pass — 0599065
- [x] 2.4 Full PostgreSQL-backed suite and coverage pass — 0599065

#### Manual

- [x] 2.5 PR synchronize event produces fresh canonical checks — 0599065

### Phase 3: Serialized Railway Release Pipeline

#### Automated

- [x] 3.1 Release verifier tests pass
- [x] 3.2 Production workflow contract tests pass
- [x] 3.3 Production workflow is trackable
- [x] 3.4 Repository static and type checks pass
- [x] 3.5 Full PostgreSQL-backed suite and coverage pass

#### Manual

- [ ] 3.6 Production environment scope, targets, and secret boundary are verified
- [ ] 3.7 Railway native main autodeploy is disabled
- [ ] 3.8 Controlled verifier failures are bounded and secret-free

### Phase 4: Production Enablement and Handoff

#### Automated

- [ ] 4.1 Active handoff documentation has no stale deployment contradictions
- [ ] 4.2 Final workflow, verifier, static, type, and PostgreSQL-backed checks pass
- [ ] 4.3 Change metadata and canonical Progress structure remain valid

#### Manual

- [ ] 4.4 First canary records a complete matching exact-SHA release chain
- [ ] 4.5 Second canary proves serialized one-deployment-per-push behavior
- [ ] 4.6 Controlled failure is visible, safe, and does not auto-rollback
- [ ] 4.7 Human rollback drill restores liveness with migration caveat recorded
- [ ] 4.8 Canary, failure, and rollback logs contain no secrets
