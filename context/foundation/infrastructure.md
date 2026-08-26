---
project: AzLimits
researched_at: 2026-07-19
recommended_platform: Railway
runner_up: Fly.io
context_type: mvp
tech_stack:
  language: Python 3.12
  framework: FastAPI
  runtime: uvicorn (ASGI)
---

## Recommendation

**Deploy on Railway.**

Railway is the strongest fit for a solo, cost-minimizing, single-region Python 3.12 / FastAPI MVP with an external database. It scores 5/5 on the agent-friendly criteria: zero-config Python auto-detection (Railpack reads `uv.lock`), a stable CLI (`railway up` / `railway logs` / `railway redeploy`), agent-readable markdown docs with `llms.txt`, and a first-class **GA MCP server** (`railway mcp install`, works with GitHub Copilot) — a decisive signal for a project whose own primary surface is an MCP tool. Its $5/mo Hobby floor with usage-based billing is the cheapest viable base among the Python-capable candidates, matching the "minimize cost" constraint, and it runs a long-lived `uvicorn` process without forcing a serverless refactor. Fly.io is a close runner-up (the starter default) but has no free tier and no first-class MCP; Render's free tier cold-starts (~1 min) would breach the PRD's <800 ms p95 target.

## Platform Comparison

Hard filters applied before scoring:

- **Cloudflare Workers — dropped (runtime).** Python is Pyodide-only: no native C extensions, no persistent process, cannot run a `uvicorn`/FastAPI ASGI server.
- **Netlify — dropped (runtime).** Python runs only under the deprecated Lambda-compatibility mode (sunset 2027-07-01); no viable FastAPI path.

| Platform | CLI-first | Managed / Serverless | Agent-readable docs | Stable deploy API | MCP / Integration | Total |
|---|---|---|---|---|---|---|
| **Railway** | Pass | Pass | Pass | Pass | Pass (GA) | **5 Pass** |
| **Fly.io** | Pass | Pass | Pass | Pass | Fail | 4 Pass |
| **Render** | Pass | Pass | Pass | Pass | Pass (GA) | 5 Pass* |
| **Vercel** | Pass | Pass | Pass | Pass | Partial (beta) | Partial fit |
| ~~Cloudflare~~ | — | — | — | — | — | Dropped (runtime) |
| ~~Netlify~~ | — | — | — | — | — | Dropped (runtime) |

\* Render scores 5 Pass on the criteria but its free tier spins down after 15 min idle (~1 min cold start), which violates the PRD's <800 ms p95 requirement; a usable configuration requires the $7/mo Starter tier plus paid Postgres.

Per-platform notes:

- **Railway** — Railpack auto-detects Python 3.12 from `uv.lock` (GA), injects `$PORT`, and runs a persistent process. CLI (`railway`, v5.x) covers deploy/logs, with rollback via `railway redeploy` or the dashboard. Docs are markdown-native (`railwayapp/docs`, `llms.txt`). Official MCP server is GA and integrates with Copilot/Claude/Cursor. Provided Postgres is **unmanaged** (backups are yours) — a non-issue here since an external managed DB is preferred. Billing is usage-based with a $5/mo floor and **no hard cap**.
- **Fly.io** — GA `flyctl` (`fly deploy` / `fly logs` / `fly releases`), markdown docs on GitHub (`superfly/docs`), deterministic deploy API. Runs FastAPI via Dockerfile. **No free tier** (removed 2024-10-07); smallest always-on machine ≈ $5.70/mo. **No first-class MCP server** (empty `/mcp` docs folder). Fly Managed Postgres is GA but starts at ~$38/mo, so co-location is uneconomical — external DB assumed.
- **Render** — Native Python runtime, GA CLI (`render deploys create` / `render rollbacks`), `render.yaml` blueprints, `llms-full.txt` docs, GA MCP (`mcp.render.com`). Blockers for this project: free web-service spin-down cold starts (~1 min, breaks p95) and free Postgres auto-deletion after 30 days. Viable only on paid tiers.
- **Vercel** — Full GA Python/ASGI *auto-detection*, excellent CLI, `llms.txt` docs, MCP in **beta**. But it runs FastAPI as a **serverless function**, not a persistent server: 300 s default timeout, ephemeral/read-only filesystem (no local SQLite), and a function-handler model that is an awkward fit for a standard `uvicorn` app with a database. Runtime fit is only Partial, so it is not shortlisted.

### Shortlisted Platforms

#### 1. Railway (Recommended)

Wins on the exact axes the interview weighted: lowest base cost ($5/mo Hobby), zero-config Python from `uv.lock` (no Dockerfile required for a solo dev with no platform familiarity), a persistent `uvicorn` process, and a **GA MCP server** that matches this project's own agent/MCP-first thesis. Single-region and external-DB answers neutralize the platforms whose main edge is global CDN or co-located data, leaving Railway's DX + cost + agent tooling ahead.

#### 2. Fly.io

The starter default and a genuinely strong option: mature GA CLI, deterministic releases, markdown docs, native IPv6/Anycast. It loses the top slot on two interview-weighted points — no free tier (a slight cost penalty vs Railway's $5 floor) and no first-class MCP integration (Railway offers a GA one). Its Dockerfile-based flow is marginally more setup for a solo dev with no familiarity. Excellent fallback if Railway's unmanaged DB or uncapped billing become dealbreakers.

#### 3. Render

Clean CLI, GA MCP, and `render.yaml` IaC make it agent-friendly on paper. It falls to third because its cheapest usable path is not the free tier: free web services cold-start (~1 min, breaching the <800 ms p95 guardrail) and free Postgres is deleted after 30 days, so a real deployment needs $7/mo Starter + paid Postgres — pricier than Railway for equivalent capability.

## Anti-Bias Cross-Check: Railway

### Devil's Advocate — Weaknesses

1. **Unmanaged provided Postgres.** Railway's one-click Postgres has no automated backups or point-in-time recovery; a bad migration against the seeded ≥100-record provenance dataset has no restore path unless backups were wired manually.
2. **Usage-based billing with no hard cap.** The $5 Hobby figure is a floor, not a ceiling; the abuse/credential-stuffing volume the PRD's NFRs call out would inflate CPU/egress metering with no automatic spend limit.
3. **Single-instance data shortcut.** Using SQLite on a Railway volume pins the service to one instance and one region permanently, foreclosing horizontal scaling later.
4. **No secrets-rotation UX beyond env vars.** The hard rule "tokens stored only as hashes, never logged" rests entirely on app-level discipline; Railway's log stream captures anything printed.
5. **Vendor-specific config.** Railpack detection, `$PORT` injection, and `railway.json` are not portable — migrating off later means rewriting the deploy layer.

### Pre-Mortem — How This Could Fail

The team shipped AzLimits on Railway in week 3 and the demo was flawless. The trouble started quietly. The "temporary" Railway Postgres became the real datastore because it was one click, and nobody configured backups. A routine re-import of the curated dataset ran against production instead of staging and truncated the verified records — with no point-in-time recovery the provenance-backed table was gone, and the CSV seed had drifted from what was live. Meanwhile a scraper hammered the public search endpoint; usage-based billing quietly tripled because no spend alert existed and the solo maintainer wasn't watching the dashboard. When they finally added a second instance for resilience, the early SQLite-on-volume shortcut meant the app couldn't run more than one replica, forcing an urgent DB migration under pressure. None of these were Railway defects — they were the predictable cost of "one-click, unmanaged, usage-metered" chosen without guardrails. The platform optimized for a fast start and silently punished the absence of backups, spend caps, and a stateless data layer.

### Unknown Unknowns

- **Railpack can silently drift the runtime.** Without a pinned `.python-version` and an explicit start command, a rebuild months later may resolve a different Python patch than `uv.lock` expects.
- **Health-check hostname must be trusted.** Railway's `RAILWAY_HEALTHCHECK` host must be allowed in FastAPI's `TrustedHostMiddleware`/allowed hosts, or zero-downtime deploys fail the health gate in a way that looks like an app bug.
- **"One-click" ≠ managed.** Railway-provided databases are unmanaged — provisioning is easy, but backups, upgrades, and failover are the developer's responsibility.
- **MCP grants broad account actions.** The GA `railway mcp install` server is powerful; scoping the token to a single project/environment is on you, in line with the PRD's least-privilege intent.
- **SQLite-on-volume is a structural ceiling.** An early convenience that permanently ties the service to one instance and one region.

## Operational Story

- **Production releases**: GitHub Actions is the selected control plane. Every
  push to `main` runs exact-SHA quality checks, then one serialized Railway CLI
  deployment, `/version` identity verification, and `/health` liveness check.
  Railway native branch autodeploy is an alternative and must remain disabled
  while the Actions-controlled workflow exists. PR preview environments remain
  out of scope.
- **Secrets**: Store `GITHUB_OAUTH_*`, DB URL, and token-hash salt as **Railway service variables** (per-environment), or reference them from a shared variable group; never commit them. They are injected as env vars at runtime. The app must never log raw values (PRD hard rule) — strip secrets from structured logs and error responses. Rotation = update the variable and redeploy; there is no dedicated rotation UI.
- **Rollback**: A human selects a known-good prior deployment in Railway and
  uses the dashboard rollback action after checking schema compatibility.
  Rollback reverts code/config only—database migrations do not roll back—so
  destructive changes require a forward fix.
- **Approval**: The GitHub Actions release is automatic after exact-SHA quality
  checks. Human-only actions include rollback, provisioning/deleting a database,
  rotating the token-hash salt or OAuth secret, and any destructive production
  import.
- **Logs**: `railway logs` (add `-n <lines>`, `--build` for build logs) streams runtime and build logs read-only; the same is available through the GA MCP server as structured tools for an agent, and in the dashboard. Ensure the minimal logging floor (request + error, secrets stripped) the PRD requires.

## Risk Register

| Risk | Source | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| Unmanaged DB loses provenance dataset (no PITR) | Devil's advocate / Pre-mortem | M | H | Use an **external managed Postgres** (Neon/Supabase free tier) with automated backups instead of Railway's one-click DB; keep the CSV seed + import script in version control as a re-seed path. |
| Usage-based billing spikes under abuse traffic | Devil's advocate / Pre-mortem | M | M | Configure a Railway **usage/spend limit and alert**; implement the PRD's rate-limiting NFR so abusive volume is rejected before it meters CPU/egress. |
| Secrets/tokens leak into logs | Devil's advocate / Research finding | L | H | Enforce the "hash-only, never log" rule in code; strip secrets from structured logs and error bodies; store values as Railway service variables, not in the repo. |
| Runtime drift on rebuild (Railpack) | Unknown unknowns | M | M | Commit a pinned `.python-version` (3.12) and an explicit start command; rely on `uv.lock` for dependency pinning; verify the resolved runtime after each deploy. |
| Health-check host rejected → failed deploy | Unknown unknowns | M | L | Add Railway's health-check host to FastAPI `TrustedHostMiddleware`/allowed hosts and point Railway's health check at `/health`; dependency-aware readiness remains pending. |
| SQLite-on-volume blocks scaling/region move | Devil's advocate / Unknown unknowns | L | M | Keep the data layer on **external Postgres** (stateless service) from day one so the app can run >1 instance and migrate regions without rework. |
| DB migration not covered by code rollback | Research finding | M | M | Treat schema migrations as forward-only; test migrations against a staging environment/PR environment before production; never run destructive imports against prod. |
| MCP token over-scoped | Unknown unknowns | L | M | Scope the `railway mcp` token to a single project/environment (least privilege), matching the PRD access-control model. |

## Current Deployment Handoff

The platform-selection research above is preserved as dated historical context.
The repository now owns the active deployment procedure in
`context/deployment/deploy-plan.md`:

1. Keep `.python-version`, `uv.lock`, and `railway.json` committed.
2. Keep application runtime secrets in Railway service variables.
3. Configure the GitHub `production` Environment with non-secret target IDs and
   HTTPS URL plus only a scoped `RAILWAY_TOKEN` secret.
4. Keep Railway native GitHub autodeploy disabled.
5. Release through `push: main`; do not use a parallel manual or native deploy
   path for routine production changes.
6. Use retained normalized evidence and the documented human rollback procedure
   for incidents. A code rollback never reverses a database migration.

## Out of Scope

The following were not evaluated in this research:
- Docker image configuration
- Production-scale architecture (multi-region, HA, DR)

CI/CD was outside this dated selection exercise but was subsequently designed
and implemented in `context/changes/deploy-pipeline/`.
