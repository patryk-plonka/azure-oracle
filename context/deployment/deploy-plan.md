---
project: AzLimits
platform: Railway
runner_up: Fly.io
planned_at: 2026-07-19
updated_at: 2026-08-26
deploy_trigger: github-actions-push-main
context_type: mvp
tech_stack:
  language: Python 3.12
  framework: FastAPI
  runtime: uvicorn (ASGI)
  package_manager: uv
database: external managed Postgres (Neon free tier)
source_docs:
  - context/foundation/infrastructure.md
  - context/foundation/tech-stack.md
  - context/changes/deploy-pipeline/plan.md
---

# Production Release Runbook — AzLimits → Railway

AzLimits releases through `.github/workflows/deploy-production.yml`. Every push
to `main`, including a merged pull request or direct push, runs the canonical
Ruff, mypy, and PostgreSQL-backed coverage workflow for the triggering full Git
SHA. A successful quality job then starts one serialized, non-canceling Railway
deployment and verifies that the running application reports that same SHA and
returns HTTP 200 from `/health`.

The workflow is fully automatic after its exact-SHA quality checks. Do not add
an environment approval timer or reviewer unless the product's automatic
release requirement is deliberately changed.

## 1. Control Plane and Prerequisites

- GitHub Actions is the only production deployment control plane.
- Railway native GitHub branch autodeploy for `main` must remain disabled. If it
  is enabled, one push can create duplicate, overlapping migration-capable
  deployments.
- `.github/workflows/pr-quality.yml` is the single canonical quality workflow;
  the production workflow calls it rather than copying its commands.
- `.python-version`, `uv.lock`, `railway.json`, `/health`, and `/version` are
  committed and covered by repository tests.
- `railway.json` runs `uv run alembic upgrade head` before Uvicorn. Migrations
  are forward-only, so production runs use fixed `railway-production`
  concurrency with cancellation disabled.
- The public hostname is present in `ALLOWED_HOSTS`, and `APP_URL` matches the
  public OAuth callback origin.

## 2. GitHub Production Environment

Create an Environment named exactly `production` with these non-secret
environment variables:

| Variable | Purpose |
| --- | --- |
| `RAILWAY_PROJECT_ID` | Intended Railway project identifier |
| `RAILWAY_ENVIRONMENT_ID` | Intended production environment identifier |
| `RAILWAY_SERVICE_ID` | Intended AzLimits service identifier |
| `APPLICATION_URL` | Credential-free public HTTPS application base URL |

Add exactly one deployment secret:

| Secret | Scope |
| --- | --- |
| `RAILWAY_TOKEN` | Railway project token restricted to the intended project/environment |

The workflow exposes `RAILWAY_TOKEN` only to `railway up` and
`railway deployment list`. Do not copy `DATABASE_URL`, GitHub OAuth secrets,
`TOKEN_HASH_SALT`, API tokens, OpenRouter credentials, authorization headers,
or any other application/provider secret into GitHub Actions.

## 3. Railway Runtime Configuration

Keep runtime configuration as Railway service variables, per environment:

| Variable | Purpose |
| --- | --- |
| `APP_URL` | Canonical public origin used for the GitHub callback URL |
| `GITHUB_OAUTH_CLIENT_ID` | GitHub OAuth application identifier |
| `GITHUB_OAUTH_CLIENT_SECRET` | GitHub OAuth application secret |
| `DATABASE_URL` | External managed PostgreSQL connection |
| `TOKEN_HASH_SALT` | API-token hashing secret |
| `ALLOWED_HOSTS` | Public and Railway health-check hosts |

Never configure `TEST_DATABASE_URL` in Railway production. Never print, copy to
evidence, or commit any variable value. The curated seed remains a separate,
human-approved operation; it never runs during deployment.

Railway uses the committed start contract:

```text
uv run alembic upgrade head && uv run uvicorn main:app --host 0.0.0.0 --port $PORT --no-access-log
```

The Railway activation health check targets `/health`.

## 4. Automatic Release Sequence

1. A `push` to `main` starts `Deploy Production` for the triggering full SHA.
2. The reusable quality job checks out that exact SHA and runs Ruff, mypy, and
   the PostgreSQL-backed test/coverage suite.
3. The deploy job enters fixed non-canceling `railway-production` concurrency
   and the `production` Environment.
4. The job checks out the same SHA with persisted credentials disabled.
5. It generates `release.json` containing exactly that SHA. The file exists in
   the uploaded source bundle but is not committed.
6. Railway CLI 5.30.1 uploads the source in attached JSON mode with explicit
   project, environment, and service targets. The SHA is also attached as the
   deployment message for provider-record correlation.
7. The workflow requires one matching `SUCCESS` deployment from
   `railway deployment list --json`.
8. `verify_release.py` checks HTTPS `/version` first and requires exact full-SHA
   equality, then checks `/health` for HTTP 200. Retries and request/overall
   timeouts are bounded.
9. The workflow writes a concise GitHub step summary and retains only normalized
   `release-evidence.json` for 30 days.

Do not add `--detach`; queueing a build is not production acceptance. Do not
introduce implicit locally linked targets or a mutable Railway CLI version.

## 5. Release Evidence

The normalized artifact and step summary record only safe release facts:

- source full Git SHA and GitHub quality/release run ID;
- Railway deployment ID, terminal status, and creation timestamp;
- observed `/version` SHA, HTTP status, attempts, and verification timestamp;
- `/health` HTTP status, attempts, and verification timestamp;
- overall success/failure state, safe failure code, and UTC timestamps.

Raw Railway logs, response bodies, provider metadata, credentials, headers, and
secret values are never retained as evidence. Treat a missing artifact, an
`unknown`/malformed/mismatched runtime SHA, ambiguous Railway record, redirect,
non-HTTPS URL, timeout, or non-200 response as a failed release.

## 6. Health and Readiness Boundary

`GET /health` is process liveness only. It is intentionally static and does not
prove PostgreSQL or another dependency is reachable. `GET /version` proves the
running source identity but is not a readiness check. Dependency-aware readiness
remains pending in `context/foundation/test-plan.md`; do not describe a green
release as proof of database readiness.

## 7. Failure Triage

1. Open the failed Actions run and read the normalized failure code and step
   summary. Compare the triggering SHA with any available evidence.
2. Download `production-release-evidence-<sha>` when present. Do not attach raw
   logs to the artifact or copy secrets into an issue.
3. Inspect the matching Railway deployment status and bounded build/runtime
   logs in Railway. Redact credentials and connection strings before sharing.
4. Determine whether failure occurred in quality, CLI installation/upload,
   Railway terminal status, `/version`, or `/health`.
5. Do not automatically roll back. Startup may already have applied a
   forward-only migration, so code/schema compatibility requires human review.

To stop future automatic releases, disable `Deploy Production` in GitHub Actions
or land a reviewed change that disables its `push: main` trigger. This does not
undo the current deployment or schema. Keep Railway native autodeploy disabled
while the Actions workflow exists, including during incident response.

## 8. Human Rollback

1. Identify the last known-good Railway deployment ID from retained evidence and
   the Railway deployment list.
2. Review migrations applied since that deployment. Confirm the prior code can
   run safely against the current schema; database migrations are not reversed.
3. In the Railway dashboard, select that prior deployment and use its rollback
   action for the intended production service/environment.
4. Confirm the resulting deployment reaches a successful terminal state.
5. Check HTTPS `/health` for liveness and `/version` for the SHA that is now
   running. A rollback intentionally reports the prior SHA.
6. Record the deployment ID, observed SHA, health result, timestamps, operator,
   and any forward-migration constraint. Review logs for secret leakage.
7. Leave the deterministic PR quality workflow enabled. Re-enable the production
   workflow only after the failure cause and schema compatibility are understood.

Never run a destructive import or down migration as an automatic rollback step.

## 9. Initial Enablement Checklist

- [ ] GitHub `production` Environment is automatic and has the four intended
      non-secret variables plus only the scoped `RAILWAY_TOKEN` deployment secret.
- [ ] Railway runtime variables contain all application secrets and no
      `TEST_DATABASE_URL`.
- [ ] Railway native GitHub autodeploy for `main` is disabled.
- [ ] Project, environment, service, HTTPS URL, OAuth origin, and allowed hosts
      identify the same production target.
- [ ] A safe canary push records one matching quality → Railway → `/version` →
      `/health` evidence chain.
- [ ] A second canary confirms non-canceling serialization and exactly one
      Railway deployment per push.
- [ ] A controlled verifier failure retains safe evidence, fails visibly, and
      does not auto-rollback.
- [ ] A human rollback drill restores liveness and records the forward-migration
      caveat.
- [ ] Actions and Railway logs for canary, failure, and rollback contain no raw
      token, OAuth credential, database URL, hash salt, authorization header, or
      provider secret.

## 10. Out of Scope

- Dependency-aware `/ready` acceptance.
- Pull-request previews, staging, canaries with traffic splitting, multi-region,
  high availability, or disaster-recovery automation.
- Automatic rollback, database down migrations, or destructive data operations.
- Railway native branch deployment alongside the Actions-controlled pipeline.
- GitHub Deployment API records or application runtime secrets in Actions.
