---
date: 2026-08-25T22:54:57+02:00
researcher: Codex
git_commit: 91ff600efeefafa78d35e534d36e8a0989063129
branch: main
repository: patryk-plonka/azure-oracle
topic: "Automatic Railway deployment after updates land on main"
tags: [research, codebase, github-actions, railway, deployment]
status: complete
last_updated: 2026-08-25
last_updated_by: Codex
---

# Research: Automatic Railway deployment after updates land on main

**Date**: 2026-08-25T22:54:57+02:00  
**Researcher**: Codex  
**Git Commit**: 91ff600efeefafa78d35e534d36e8a0989063129  
**Branch**: main  
**Repository**: patryk-plonka/azure-oracle

## Research Question

How should AzLimits add a pipeline that automatically deploys to Railway after
a pull request is merged or code is pushed directly to `main`?

Seed intent: "add new pipeline to triger automatic deployment to railway after
pr merged or push to main".

## Summary

Use one GitHub Actions trigger: `push` restricted to `main`. A merged pull
request already creates a push to `main`; combining that event with
`pull_request: closed` would deploy the same commit twice. Direct pushes to
`main` should intentionally use the same path.

The repository is deployable today: Python is pinned to 3.12, dependencies are
locked, Railway runs Alembic before Uvicorn, and `/health` is its activation
gate. The missing piece is a secure, exact-SHA deployment gate. Current quality
CI runs only when a pull request is opened or becomes ready, so it neither
checks later PR updates nor the final commit pushed to `main`.

The recommended design is a new `push: main` deployment workflow that reuses
the canonical Ruff, mypy, and PostgreSQL/coverage jobs, then runs one serialized
Railway deployment only after they pass. The deployment job should use a GitHub
Environment named `production`, an environment-scoped Railway project token,
explicit project/service/environment targets, an exactly pinned Railway CLI,
and a step-scoped `RAILWAY_TOKEN`. Runtime secrets remain in Railway and must
never be copied into GitHub Actions.

Railway's native GitHub autodeploy is a viable alternative and can wait for
GitHub CI, but it must not remain enabled if Actions also invokes `railway up`.
One push must have exactly one deployment control plane.

## Detailed Findings

### Trigger and exact-SHA quality gate

- One `push` event on `main` covers merged pull requests and direct pushes.
  Adding a second merged-PR event expands the trust surface and duplicates
  deployments.
- The existing quality workflow listens only for `opened` and
  `ready_for_review`; it does not run for `synchronize` or `push`
  ([`.github/workflows/pr-quality.yml:1-10`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/.github/workflows/pr-quality.yml#L1-L10)).
  A deploy cannot safely treat its earlier PR result as proof for the exact
  commit now on `main`.
- The canonical checks already exist as three independent jobs: Ruff, mypy,
  and PostgreSQL-backed pytest with the coverage floor
  ([`.github/workflows/pr-quality.yml:11-61`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/.github/workflows/pr-quality.yml#L11-L61)).
  Add `workflow_call` to make these jobs reusable, then have the deployment
  workflow call them and make `deploy` depend on their success. This checks the
  exact pushed SHA without maintaining two drifting command lists.
- Branch protection remains valuable for preferring reviewed merges, but the
  requested direct-push behavior means the deployment workflow itself must be
  safe even when a commit did not arrive through a PR.

### Railway runtime is ready, with a readiness gap

- Railway currently starts with `uv run alembic upgrade head` followed by
  Uvicorn on Railway's injected `$PORT`; `/health` is the configured deployment
  health check
  ([`railway.json:1-6`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/railway.json#L1-L6)).
- Python is pinned to 3.12
  ([`.python-version:1`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/.python-version#L1)),
  `uv.lock` is tracked, and the production dependencies include Alembic,
  FastAPI, psycopg, SQLAlchemy, and Uvicorn
  ([`pyproject.toml:6-15`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/pyproject.toml#L6-L15)).
- Startup requires `APP_URL`, both GitHub OAuth values, `TOKEN_HASH_SALT`, and
  `DATABASE_URL`
  ([`main.py:55-70`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/main.py#L55-L70),
  [`database.py:14-27`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/database.py#L14-L27)).
  These values belong in Railway service variables. GitHub needs only the
  deployment token and non-secret target identifiers.
- `ALLOWED_HOSTS` defaults to local hosts and Railway's health-check host
  ([`main.py:88-90`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/main.py#L88-L90)).
  The public Railway/custom hostname must also be configured for real traffic,
  while `APP_URL` must match the OAuth callback origin.
- `/health` is static and does not query PostgreSQL
  ([`main.py:188-190`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/main.py#L188-L190)).
  Railway therefore proves process activation, not ongoing dependency
  readiness. The test strategy already calls for readiness to fail when the DB
  is unreachable
  ([`context/foundation/test-plan.md:83-96`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/context/foundation/test-plan.md#L83-L96)).
  A dependency-aware `/ready` endpoint is the strongest post-deploy smoke gate;
  otherwise the first version can smoke-test HTTPS `/health` and explicitly
  document that limitation.

### Authentication and secret boundary

- Current Railway guidance distinguishes project-scoped `RAILWAY_TOKEN` from
  broader account/workspace `RAILWAY_API_TOKEN`. Automated deployment needs the
  project token only. Railway documents non-interactive project-token use with
  `railway up` in its [CLI authentication guide](https://docs.railway.com/cli/login)
  and [deployment guide](https://docs.railway.com/cli/deploying).
- Store `RAILWAY_TOKEN` in a GitHub Environment named `production`, not as a
  repository-wide runtime variable. Expose it only on the `railway up` step,
  following the repository's existing worker-step-only secret pattern
  ([`.github/workflows/pr-ai-review.yml:24-38`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/.github/workflows/pr-ai-review.yml#L24-L38)).
- Use non-secret GitHub Environment variables for the Railway project,
  environment, service, and public application URL. Explicit targeting avoids
  prompts and accidental deployment to a developer-linked project. Railway's
  current CLI supports `--project`, `--environment`, and `--service`; when
  `--project` is supplied, `--environment` is required
  ([official `railway up` reference](https://docs.railway.com/cli/up)).
- Do not pass `DATABASE_URL`, OAuth secrets, `TOKEN_HASH_SALT`, OpenRouter
  credentials, or application bearer tokens through the deployment workflow.
  The README already forbids production `TEST_DATABASE_URL`
  ([`README.md:119-132`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/README.md#L119-L132)).
- Pin the Railway CLI to an exact reviewed version rather than using a mutable
  `latest` container or unversioned installer. The official CLI release stream
  is available at [`railwayapp/cli` releases](https://github.com/railwayapp/cli/releases).

### Deployment serialization, health, and rollback

- Use fixed workflow concurrency such as `railway-production` with
  `cancel-in-progress: false`. Every release runs Alembic before serving, so
  overlapping deploys can overlap migrations, while canceling an in-flight
  deployment can interrupt a migration-capable operation.
- Use `railway up --ci` in attached CI mode and fail the GitHub job when Railway
  reaches a failed terminal state. Do not use `--detach` as the success signal;
  it proves only that a build was queued. Railway documents these semantics and
  exit codes in the [`railway up` reference](https://docs.railway.com/cli/up).
- After Railway succeeds, retry `GET <public-url>/health` over HTTPS with a
  bounded timeout. Railway health checks gate traffic activation but do not
  continuously monitor the service afterward
  ([Railway health-check documentation](https://docs.railway.com/deployments/healthchecks)).
- Rollback restores code/config, not database schema. Migrations are
  forward-only and destructive imports remain human-only
  ([`context/deployment/deploy-plan.md:141-156`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/context/deployment/deploy-plan.md#L141-L156)).
  Automatic rollback should not be added until migration compatibility rules
  are explicit; begin with visible failure, retained prior deployment, and a
  documented human rollback command.

### Workflow permissions, tracking, and tests

- The deployment workflow needs only `contents: read` at GitHub level. It does
  not need `pull-requests: write`, `deployments: write`, or OIDC unless the
  implementation later adopts a mechanism that explicitly requires them.
- Checkout should use the existing immutable action SHA and disable persisted
  credentials. Existing workflow tests already encode immutable checkout and
  setup-uv references
  ([`tests/test_pr_workflows.py:9-13`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/tests/test_pr_workflows.py#L9-L13)).
- `.github/**` is ignored except for explicitly allowlisted assets. A new
  workflow will remain untrackable until `.gitignore` adds its exact path
  ([`.gitignore:27-34`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/.gitignore#L27-L34)).
- Extend `tests/test_pr_workflows.py` to assert the exact `push: main` trigger,
  read-only permissions, reusable quality dependency, immutable actions,
  pinned CLI, fixed non-canceling concurrency, `production` environment,
  step-scoped Railway token, absence of runtime/provider secrets, exact target
  arguments, and bounded post-deploy smoke check. The existing ignore test also
  needs the new workflow in its intended trackable set
  ([`tests/test_pr_workflows.py:96-111`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/tests/test_pr_workflows.py#L96-L111)).

### Exactly one deployment control plane

- Railway can natively deploy every push to a connected branch and can wait for
  GitHub Actions checks before proceeding
  ([Railway GitHub autodeploy documentation](https://docs.railway.com/deployments/github-autodeploys)).
- If the new GitHub Actions workflow runs `railway up`, disable Railway native
  branch autodeploy first. Leaving both enabled produces two deployments per
  main push and can overlap migrations.
- Native autodeploy plus "Wait for CI" is a credible alternative with a smaller
  GitHub secret surface, but it moves the decisive deployment configuration to
  the Railway dashboard. The requested repository-owned pipeline favors the
  explicit Actions-controlled option.

## Code References

- [`railway.json:1-6`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/railway.json#L1-L6) — migration, start command, and activation health check.
- [`.github/workflows/pr-quality.yml:1-61`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/.github/workflows/pr-quality.yml#L1-L61) — current deterministic checks and incomplete event coverage.
- [`.github/workflows/pr-ai-review.yml:11-38`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/.github/workflows/pr-ai-review.yml#L11-L38) — concurrency, immutable checkout, and step-scoped secret precedent.
- [`main.py:55-105`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/main.py#L55-L105) — production configuration and trusted hosts.
- [`main.py:188-205`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/main.py#L188-L205) — static health and OAuth route boundary.
- [`database.py:14-36`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/database.py#L14-L36) — mandatory PostgreSQL configuration.
- [`.gitignore:27-34`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/.gitignore#L27-L34) — exact GitHub asset allowlist.
- [`tests/test_pr_workflows.py:47-111`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/tests/test_pr_workflows.py#L47-L111) — current workflow and tracking contracts.
- [`context/deployment/deploy-plan.md:66-156`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/context/deployment/deploy-plan.md#L66-L156) — Railway variables, deployment, verification, and rollback policy.

## Architecture Insights

The deployment workflow should be a release boundary, not another loosely
related CI script. Its dependency chain is:

```text
push to main (merged PR or direct push)
          |
          v
exact-SHA reusable quality workflow
  Ruff + mypy + PostgreSQL tests/coverage
          |
          v
serialized production deployment
  pinned Railway CLI + scoped project token
          |
          v
Railway build -> Alembic -> Uvicorn -> /health activation
          |
          v
bounded HTTPS post-deploy smoke check
```

This keeps three trust zones distinct: untrusted PR code is tested without
production credentials; the exact trusted `main` SHA is revalidated; only the
final deployment step receives the project-scoped Railway token. Application
runtime secrets never cross into GitHub.

The recommended workflow contract is:

1. `on.push.branches: [main]` only.
2. `permissions: {contents: read}`.
3. fixed `railway-production` concurrency with cancellation disabled.
4. call the reusable quality workflow for the triggering SHA.
5. deploy from a clean checkout of that SHA using an exactly pinned CLI.
6. target the production project, environment, and service explicitly.
7. expose only `RAILWAY_TOKEN` to the deploy command.
8. await Railway success, then perform a bounded HTTPS smoke check.
9. preserve the previous deployment for human rollback; never pretend code
   rollback reverses migrations.

## Historical Context (from prior changes)

- The first Railway deploy was deliberately human-gated and CI/CD was parked as
  a follow-up
  ([`context/deployment/deploy-plan.md:19-39`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/context/deployment/deploy-plan.md#L19-L39)).
  This change is that follow-up.
- Commit `8f906ec` added the deployable FastAPI skeleton, Python pin, Railway
  configuration, and health endpoint. Archived progress records manual Railway
  deployment and health verification, but that is human attestation rather
  than a reproducible Actions run
  ([`context/archive/2026-07-20-deploy-skeleton-health/plan.md:137-146`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/context/archive/2026-07-20-deploy-skeleton-health/plan.md#L137-L146)).
- Commit `18ff786` introduced deterministic PR quality CI; the archived pipeline
  research established immutable action pinning, disposable PostgreSQL, and
  separate secret trust profiles
  ([`context/archive/2026-08-25-pr-pipeline/research.md`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/context/archive/2026-08-25-pr-pipeline/research.md)).
- `context/foundation/tech-stack.md` still names Fly.io even though the later
  infrastructure decision and tracked `railway.json` establish Railway as the
  current target. `context/deployment/deploy-plan.md` also retains obsolete
  entry-gate text describing `main.py` as a stub. Planning should correct these
  stale handoff documents rather than treating them as current truth.
- The test plan explicitly says deployment plumbing must be reconsidered when
  auto-deploy-on-merge lands
  ([`context/foundation/test-plan.md:198-205`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/context/foundation/test-plan.md#L198-L205)).

## Related Research

- [`context/foundation/infrastructure.md`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/context/foundation/infrastructure.md) — platform choice, Railway risks, secret handling, health, and rollback.
- [`context/archive/2026-08-25-pr-pipeline/research.md`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/context/archive/2026-08-25-pr-pipeline/research.md) — GitHub Actions trust boundaries and workflow testing patterns.
- [`context/archive/2026-07-20-deploy-skeleton-health/plan.md`](https://github.com/patryk-plonka/azure-oracle/blob/91ff600efeefafa78d35e534d36e8a0989063129/context/archive/2026-07-20-deploy-skeleton-health/plan.md) — original deployable runtime and Railway health contract.

## Open Questions

1. Is Railway native GitHub autodeploy currently enabled for `main`? It must be
   disabled before an Actions-controlled `railway up` workflow is enabled.
2. What are the production Railway project ID, environment name/ID, service
   name/ID, and public URL? Store non-secret identifiers as GitHub Environment
   variables and verify them manually before enabling the trigger.
3. Has a project/environment-scoped Railway token been created, and can its
   permissions deploy and read deployment status without broader workspace
   administration?
4. Should dependency-aware `/ready` be included in this change, or should the
   first deployment workflow explicitly accept `/health` as a liveness-only
   smoke check and leave readiness to the test-plan rollout?
5. Should `pr-quality.yml` also add `synchronize` so PR feedback stays fresh,
   independently of the mandatory exact-SHA checks on `main`?
6. Which exact Railway CLI release will be validated and pinned during
   implementation? The locally installed CLI was 5.27.0 during research, while
   the official release stream had advanced; the plan should pin the version it
   tests rather than assume local or `latest` behavior.
7. Is a GitHub Environment approval required for production, or is the desired
   policy fully automatic after exact-SHA quality passes? The user's stated goal
   favors automatic deployment, but environment protection rules remain an
   operator choice.
