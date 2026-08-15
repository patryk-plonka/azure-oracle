---
project: AzLimits
platform: Railway
runner_up: Fly.io
planned_at: 2026-07-19
deploy_trigger: manual-cli
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
---

# Deploy Plan — AzLimits → Railway (first deployment)

Human-gated first-deploy audit trail: the record of *what is supposed to happen*
when AzLimits is deployed to **Railway** with an **external Neon Postgres**, per
`infrastructure.md` and `tech-stack.md`. The first deploy is a **manual
`railway up`**; CI auto-deploy-on-merge is a documented follow-up. This document
does not build the application — a deployable FastAPI app is an **entry gate**.

## Decisions

- **App build is a prerequisite (entry gate)**, not part of this plan. `main.py`
  is currently a hello-world stub with no FastAPI `app` object or `/health`
  endpoint; deploy is blocked until that gate is met.
- **External managed Postgres now** (Neon free tier) wired as `DATABASE_URL` —
  matches the `infrastructure.md` risk-register mitigation (avoid Railway's
  unmanaged one-click DB).
- **Migrate before serving** — Railway runs `uv run alembic upgrade head` before
  Uvicorn starts. The curated seed remains an explicit human-approved command;
  it is never run during startup or deployment.
- **Manual CLI `railway up`** for the first deploy (human-gated). GitHub Actions
  auto-deploy is out of scope for this deploy, noted as a follow-up.

## 1. Entry Gates (prerequisites)

All must be true before any deploy command runs:

- [ ] A deployable FastAPI `app` object exists (e.g. `main:app`) — replaces the
      current hello-world stub in `main.py`.
- [ ] A `/health` endpoint (and readiness check) is implemented (FR-013).
- [ ] `uv.lock` is committed (Railpack reads it to detect Python + deps).
- [ ] `.python-version` pins `3.12` (already present — runtime-drift mitigation).
- [ ] HTTPS-only, secrets-stripped logging floor honored in app code (PRD NFRs).

## 2. Manual Setup Gates (human-only)

Performed by a human, out of band, before deploy:

1. **Railway account + project** — create the account and an empty project;
   choose the single region (single-region MVP).
2. **Neon managed Postgres** — provision a free-tier Postgres instance, copy the
   pooled connection string for `DATABASE_URL`. Automated backups belong to Neon
   (mitigates the "unmanaged DB, no PITR" risk).
3. **GitHub OAuth app** — register the OAuth app (FR-001); set the callback URL
  to `<APP_URL>/auth/callback`; capture client ID + secret.
4. **Spend limit + alert** — configure a Railway usage/spend limit and alert
   (mitigates uncapped usage-based billing under abuse traffic).

## 3. Secrets

All set as **Railway service variables** (per-environment), never committed to the
repo, never printed to logs or error bodies (PRD hard rule):

| Variable | Purpose | Source |
|---|---|---|
| `APP_URL` | Canonical public application origin used to build the GitHub callback URL | Railway public domain |
| `GITHUB_OAUTH_CLIENT_ID` | GitHub OAuth (FR-001) | GitHub OAuth app |
| `GITHUB_OAUTH_CLIENT_SECRET` | GitHub OAuth (FR-001) | GitHub OAuth app |
| `DATABASE_URL` | External Neon Postgres connection | Neon dashboard |
| `TOKEN_HASH_SALT` | API-token hashing (FR-004, hash-only) | generated secret |

Rotation = update the variable and redeploy (Railway has no dedicated rotation
UI). Rotating the token hash salt or OAuth client secret is a **human-only**
action (see §9). Do not commit or print any variable values, including OAuth
credentials and `TOKEN_HASH_SALT`.

`OAuthState` stores the short-lived callback state before identity is known.
User-owned `AuthGrant` rows store the short-lived onboarding and token-issuance
credentials. Both boundaries retain hashes only; no raw bearer value is stored.

## 4. Railway Configuration

- **Start command**: `uv run alembic upgrade head && uv run uvicorn main:app --host 0.0.0.0 --port $PORT`
  — applies forward-only migrations before Uvicorn starts; do **not** hard-code
  the port, and do **not** append the seed command. Railway injects `$PORT`.
- **Builder**: Railpack auto-detects `uv` from the committed `uv.lock` and runs
  `uv sync` at build — no Dockerfile required.
- **Health check**: point Railway's health check at `/health`.
- **Trusted host**: add Railway's health-check host to FastAPI
  `TrustedHostMiddleware` / allowed hosts, or zero-downtime deploys fail the
  health gate in a way that looks like an app bug.
- **Runtime pin**: `.python-version` = `3.12` + `uv.lock` keep Railpack from
  drifting to a different interpreter on rebuild.

## 5. Agent-Owned Automated Steps

An agent may run these unattended with a **project-scoped** token:

1. Install the CLI: `npm i -g @railway/cli`
   (or PowerShell: `iwr https://railway.app/install.ps1 | iex`).
2. `railway login`
3. `railway init` (create/link the project) — or `railway link` to an existing one.
4. Set variables without echoing secret values: `APP_URL`,
  `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`, `DATABASE_URL`, and
  `TOKEN_HASH_SALT`.
5. Deploy: `railway up`
6. Tail logs: `railway logs` (`--build` for build logs, `-n <lines>` to limit).

## 5.1 Database Migration and Seed Procedure

After Neon is provisioned and its connection string is set as `DATABASE_URL`:

1. Deploy or run `uv run alembic upgrade head` to apply forward-only migrations.
2. As a human-approved operator action, run
  `uv run python seed.py concept/azure_limitations_db.csv` once.
3. Review only the reported source and limitation counts; the command never
  prints the connection string.
4. Re-running the command is safe and updates records in place. It does not
  truncate data or execute automatically during deployment.

## 6. Verification

After `railway up` completes:

- [ ] Build resolved **Python 3.12** (check build logs against `uv.lock`).
- [ ] `GET /health` returns `200` over **HTTPS** at the Railway URL.
- [ ] The running service can reach the Neon Postgres (`DATABASE_URL`).
- [ ] `APP_URL` matches the public origin and GitHub callback URL exactly.
- [ ] `GET /auth/eula` serves the packaged Demo terms after startup.
- [ ] Search/query p95 **< 800 ms** over the seeded dataset (PRD NFR).
- [ ] No secret or token value appears in build or runtime logs.
- [ ] EULA/license events are logged (secrets stripped) per the logging floor.

## 7. Rollback

- Code/config: `railway deployment list` → `railway redeploy` a prior deployment
  (or the dashboard "Rollback" action). Time-to-revert ≈ one build cycle.
- **Database migrations do NOT roll back with code** — treat schema migrations as
  forward-only and forward-fix destructive changes. Never run destructive imports
  against production.

## 8. Approval Boundary

- **Agent may (unattended, scoped token)**: `railway up`, tail logs, roll back
  code via CLI/MCP.
- **Human-only**: provisioning/deleting a database, rotating the `TOKEN_HASH_SALT`
  or OAuth secret, and any destructive data import against production.
- If the Railway MCP server is installed, scope its token to a single
  project/environment (least privilege, per the PRD access-control model).

## 9. Risks (carried from infrastructure.md)

| Risk | Mitigation in this plan |
|---|---|
| Unmanaged DB loses provenance data (no PITR) | Use external **Neon** Postgres with automated backups; keep CSV seed + import script in VCS as a re-seed path. |
| Usage-based billing spikes under abuse | Railway spend **limit + alert**; enforce the PRD rate-limiting NFR. |
| Secrets/tokens leak into logs | Hash-only rule in code; strip secrets from logs/errors; secrets as Railway variables only. |
| Runtime drift on rebuild (Railpack) | `.python-version` = 3.12 + `uv.lock`; verify resolved runtime post-deploy. |
| Health-check host rejected → failed deploy | Add Railway health-check host to FastAPI allowed hosts; point health check at `/health`. |
| SQLite-on-volume blocks scaling/region move | Keep data on **external Postgres** (stateless service) from day one. |
| DB migration not covered by code rollback | Forward-only migrations; test in a PR/staging environment first. |
| MCP token over-scoped | Scope the `railway mcp` token to one project/environment. |

## 10. Out of Scope

- Docker image configuration.
- CI/CD pipeline (GitHub Actions auto-deploy-on-merge) — documented follow-up.
- Production-scale architecture (multi-region, HA, DR).
