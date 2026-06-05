# Azure Limitations Intelligence Service — Concept Description

Date: 2026-06-05
Status: Concept (builds on the validated 93-record POC)
Working name: **AzLimits** (Azure Limitation Intelligence)

## 1. Summary

A small, mostly-serverless service that continuously discovers, normalizes, and
serves a structured database of **Azure service limitations** — unsupported
scenarios, known issues, quotas, preview/gated behavior, deprecations, and
workarounds — sourced from Microsoft Learn, troubleshoot pages, and product
GitHub repos. The POC proved the extraction-and-normalization pipeline works
(93 records, 14 services, full metadata schema, per-row provenance). This
concept describes how to turn that one-shot POC into a maintained product with
fresh data, an API, access control, and an MCP server so AI coding agents can
query it directly while writing Infrastructure-as-Code.

### Why it exists
There is **no canonical Azure limitations database**. The information is
scattered across docs, troubleshoot pages, GitHub issues, and blogs. Engineers
(and AI coding agents) repeatedly hit "this isn't supported" only at deploy
time. AzLimits makes that knowledge queryable *before* code is written.

## 2. Component 1 — Periodic ingestion workflow

A scheduled pipeline that re-crawls the seed sources, extracts limitations into
the fixed schema, and diffs against the current dataset.

| Aspect | Choice | Rationale |
|---|---|---|
| Trigger | Scheduled job (daily for docs, 6–12h for GitHub issues) | Azure lifecycle moves fast; numeric limits and preview status change |
| Source list | Versioned `sources.yaml` seed file (URL + service + source_type + parser hint) | Source discovery kept separate from classification, per the inventory guidance |
| Extraction | `fetch_url` + LLM table-extraction (proven in POC) for docs; `gh` CLI for repo issues/labels | Handles heterogeneous page layouts that a regex scraper can't |
| Normalization | Map to the 20-column schema; assign `support_status`, `confidence` | Learn docs = high confidence; GitHub issues = medium until corroborated |
| Change detection | Diff on `quote` / numeric value per `id`; update `first_seen` / `last_seen`; flag added/removed/changed | Enables a changelog and "what changed this week" feed |
| Idempotency | Stable `id` derived from `service + feature + source_url` hash | Re-runs update rather than duplicate |
| Orchestration | GitHub Actions cron (cheapest) **or** Azure Container Apps Job / Function timer | Stay inside the ecosystem the data describes |

Pipeline stages: `discover → fetch → extract → normalize → validate → diff →
publish → notify`. A validation gate rejects rows missing `service`,
`support_status`, `source_url`, or `quote`.

## 3. Component 2 — Storage / hosting of findings

A layered approach: a Git-tracked source of truth plus a query-optimized store.

| Layer | Format | Purpose |
|---|---|---|
| **Source of truth** | Flat files in Git: `azure_limitations.csv` + `.jsonl` (one record per line) | Human-diffable, PR-reviewable, free history/audit trail, trivial backup |
| **Query store** | **SQLite** (single file, FTS5 full-text index) | Zero-ops, fast filtering by service/status/region/SKU, ships with the API container |
| **Optional upgrade** | Postgres (Azure Database for PostgreSQL Flexible Server) | Only if multi-writer / large scale is needed later |
| **Static export** | Published `db.sqlite` + `data.csv` artifact per run | Lets consumers download the whole dataset; powers offline/CLI use |

Recommendation: **start with Git (CSV+JSONL) as truth and SQLite as the served
copy.** This keeps the whole service in one repo, costs almost nothing, and the
SQLite file rebuilds deterministically from the flat files on each run.

## 4. Component 3 — API with GitHub login + rate limiting

A small read-only REST/JSON API over the SQLite dataset.

### Endpoints (read-only v1)
- `GET /v1/limitations` — list/filter by `service`, `support_status`,
  `limitation_type`, `region`, `sku_tier`, `confidence`, `q` (full-text)
- `GET /v1/limitations/{id}` — single record with full provenance
- `GET /v1/services` — distinct services + counts
- `GET /v1/changes?since=YYYY-MM-DD` — added/changed/removed since a date
- `GET /v1/meta` — dataset version, last crawl time, record count
- `GET /healthz` — liveness

### Auth — GitHub-based, to rate-limit access
- **GitHub OAuth device/web flow** issues a short-lived token; the API maps the
  GitHub user/identity to a tier. No passwords stored.
- Alternative for machine clients: **personal API keys** minted after GitHub
  login (hashed at rest).
- Rate limits per identity tier (token-bucket), e.g. anonymous 30 req/h,
  authenticated 1,000 req/h, internal 10,000 req/h. Limits returned via
  `X-RateLimit-*` headers; `429` with `Retry-After` on breach (mirrors how
  Azure's own APIs throttle — see the ARM `SubscriptionRequestsThrottled` row in
  the dataset).
- **Why GitHub:** the audience already has GitHub accounts, it removes
  credential management, and it lets us attribute/limit usage cheaply.

### Stack
FastAPI (Python) or a thin Node service in an **Azure Container App**
(scale-to-zero) or Function. Stateless; the SQLite file is baked into the image
or pulled from blob storage on cold start.

## 5. Component 4 — MCP server + CLI + skill (agent access)

Goal: let AI coding agents (Cursor, Claude Code, Copilot, etc.) check Azure
limitations *while generating IaC*, so they avoid unsupported patterns.

### Recommendation: build the MCP server as a **thin wrapper over the API**, and ship a CLI + a skill from the same core.
All three share one query library; only the surface differs. This is the most
robust and maintainable option because there is a single source of logic.

| Surface | Use case | Maintenance cost |
|---|---|---|
| **MCP server** (recommended primary) | Agents call tools like `search_limitations(service, status, query)`, `get_limitation(id)`, `check_resource(resource_type, scenario)` directly in-context | Low — wraps the API; the MCP spec is stable and widely supported |
| **CLI** (`azlimits query ...`) | CI checks, scripts, humans, agents that prefer shell; can run fully offline against the exported SQLite | Low — same query lib, no network needed for offline mode |
| **Agent Skill** | Drop-in instructions telling an agent *when/how* to consult AzLimits (via MCP or CLI) and how to interpret `support_status`/`confidence` | Very low — markdown only; complements rather than replaces the above |

**Why MCP as primary:** it is the most natural fit for "instruct AI coding
agents to use the data" — the agent discovers the tools, calls them with
structured args, and gets structured results inline. The CLI is the robust
fallback (offline, deterministic, CI-friendly), and the skill is the cheap glue
that teaches agents the workflow. Build the MCP server first, expose the CLI
from the same package, and write a short skill last.

### Example MCP tools
- `search_limitations(filters)` → rows
- `check_support(resource_type, feature, scenario)` → best-match support_status + workaround + source
- `list_changes(since)` → recent deltas
- `get_meta()` → dataset freshness

## 6. Component 5 — Anything else (recommended additions)

1. **Confidence + provenance are first-class.** Every record keeps the exact
   quote and `source_url`; agents and humans can verify. Surface `confidence`
   in every API/MCP response so consumers can choose "docs-only" (high) vs.
   "include community/issue signal" (medium).
2. **Changelog / subscriptions.** A `/v1/changes` feed plus optional webhook or
   email/RSS digest ("3 new AKS limitations, 1 Functions deprecation this
   week"). High value for platform/FinOps teams.
3. **Coverage expansion roadmap.** Add medium-trust tiers (Microsoft Q&A, Tech
   Community, Azure OSS blogs) as discovery-only, flagged low-confidence until
   mapped to a Microsoft-owned source. Add the Azure deprecation aggregators for
   lifecycle joins.
4. **Stale-data guardrails.** Show `last_seen` everywhere; auto-flag records not
   re-confirmed in N crawls as `stale` so consumers don't trust rotted data.
5. **Lightweight UI (optional).** A static search page over the same SQLite/API
   for humans who don't want the CLI/MCP.
6. **CI integration pattern.** Ship a sample GitHub Action / pre-commit hook:
   "scan this Bicep/Terraform for resources/features that AzLimits flags as
   unsupported/gated/deprecated" — turns the dataset into a guardrail.
7. **Cost & ops.** Whole service fits in: 1 Git repo, 1 scheduled job, 1
   scale-to-zero container, 1 SQLite file. Near-zero idle cost; no database
   server to babysit.
8. **Legal/attribution note.** Content is quoted from Microsoft docs/GitHub;
   store source URLs and keep quotes short/fair-use; link back rather than
   mirror large text.

## 7. Suggested phasing

| Phase | Deliverable |
|---|---|
| 0 (done) | POC: extraction pipeline + 93-record schema + provenance |
| 1 | `sources.yaml` + scheduled ingestion + Git/SQLite storage + diff/changelog |
| 2 | Read-only API + GitHub OAuth + rate limiting |
| 3 | MCP server (primary) + CLI (from same core) |
| 4 | Agent skill + CI guardrail sample + changes feed |
| 5 | Coverage expansion (Q&A/blogs), optional UI, stale-data flags |

## 8. Architecture at a glance

```
 sources.yaml ─► [Ingestion job: fetch → extract(LLM) → normalize → validate → diff]
                         │
                         ▼
        Git (CSV + JSONL, source of truth)  ──build──►  SQLite (FTS5, served copy)
                         │                                      │
                         ▼                                      ▼
                  Changelog feed                        [Read-only API]
                                                  GitHub OAuth + rate limiting
                                                          │        │
                                              ┌───────────┘        └───────────┐
                                              ▼                                ▼
                                       [MCP server]                       [CLI / offline]
                                       (AI coding agents)            (CI, scripts, humans)
                                              ▲
                                       [Agent skill: when/how to use it]
```
