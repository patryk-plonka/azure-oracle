# azure-oracle
A small, mostly-serverless service that continuously discovers, normalizes, and serves a structured database of Azure service limitations — unsupported scenarios, known issues, quotas, preview/gated behavior, deprecations, and workarounds.

## Database Operations

Use `DATABASE_URL` only for a local operator environment or the Railway service.
It is never required for the PostgreSQL test suite.

```powershell
$env:DATABASE_URL = "postgresql://..."
uv run alembic upgrade head
uv run python seed.py concept/azure_limitations_db.csv
```

The seed command reports only source and limitation counts. It is repeatable and
does not run during application startup or deployment.

## Tests

Set `TEST_DATABASE_URL` to a disposable PostgreSQL database distinct from the
operator or Railway database. The test fixture runs migrations and truncates only
that test database between import cases. Synchronize the locked development
environment before running the same checks as pull request CI.

```powershell
$env:TEST_DATABASE_URL = "postgresql://..."
uv sync --locked --group dev
uv run ruff check .
uv run mypy .
uv run pytest tests/ -v --cov --cov-branch --cov-report=term-missing
```

Coverage measures application modules with line and branch coverage; tests,
migrations, caches, and generated metadata are excluded in `pyproject.toml`.
The `[tool.coverage.report] fail_under` value is the current whole-number
baseline. Raise it as coverage improves. Lowering it requires an explicit,
reviewed policy change rather than an incidental test or workflow edit.

## Production Releases

Every push to `main` runs the canonical Ruff, mypy, and PostgreSQL-backed
coverage workflow for the triggering full Git SHA. After those checks pass,
`.github/workflows/deploy-production.yml` creates one serialized,
non-canceling Railway production deployment, verifies its exact runtime SHA,
and checks process liveness.

`GET /version` is public and returns only `{"git_sha": "<value>"}` with
`Cache-Control: no-store`. A normal local checkout has no generated
`release.json`, so it reports `unknown`. The deployment workflow generates
`release.json` with the triggering full SHA inside the Railway upload context;
hosted verification rejects `unknown`, abbreviated, malformed, or mismatched
values.

`GET /health` remains a static liveness endpoint. HTTP 200 proves the process is
serving requests; it does not prove PostgreSQL readiness. Dependency-aware
readiness remains a separate pending obligation.

The GitHub Environment must be named `production`. Configure these non-secret
variables without documenting their values:

- `RAILWAY_PROJECT_ID`
- `RAILWAY_ENVIRONMENT_ID`
- `RAILWAY_SERVICE_ID`
- `APPLICATION_URL` (credential-free HTTPS origin)

Configure only the project/environment-scoped `RAILWAY_TOKEN` as the deployment
secret. Application runtime secrets—including `DATABASE_URL`, GitHub OAuth
credentials, and `TOKEN_HASH_SALT`—remain in Railway. Railway native GitHub
autodeploy for `main` must remain disabled so one push has one deployment
control plane.

Each run writes a safe summary and retains `release-evidence.json` for 30 days.
Evidence contains the source SHA, GitHub run ID, Railway deployment ID/status,
observed runtime SHA, health result, attempts, and UTC timestamps. It excludes
raw Railway logs, response bodies, credentials, authorization headers, and
provider metadata.

Failed deployment or verification does not roll back automatically because
startup may already have applied a forward-only Alembic migration. Follow the
human rollback procedure in `context/deployment/deploy-plan.md`: assess schema
compatibility, roll back to a prior Railway deployment, then verify `/version`
and `/health` and record non-secret evidence.

## AI PR Review Worker

`pr_review.py` is a one-shot, advisory pull request review worker. GitHub
Actions is its deployment target: a pull request event starts a fresh hosted
runner, the trusted base-branch worker reads bounded PR metadata and patches
through GitHub REST, calls OpenRouter REST, validates the structured result,
and creates or updates one marked timeline comment. The runner is destroyed
after the job. There is no OpenRouter or GitHub SDK, agent framework, GitHub
App, container, webhook service, queue, database, or persistent bot to operate.

The worker reviews at most 50 files and 64 KiB of UTF-8 input. It reports
binary, omitted, and truncated content, caps structured findings and output,
and treats all PR text and model output as untrusted data. Reviews are
informational only; humans retain merge authority. Empty or entirely binary
diffs receive an incomplete-review notice without a provider call. Provider,
configuration, or validation failures produce only a safe unavailable notice
when GitHub publication remains possible, and always require human review.

The supported rollout scope is public, same-repository, non-draft pull
requests. Private repositories, forks, and drafts are skipped by the workflow
added in the publication phase. Provider privacy controls are defense in depth,
not approval to send private code.

Safe repository configuration consists of:

- `OPENROUTER_MODEL`, an explicit structured-output-capable repository variable.
- `OPENROUTER_API_KEY`, a dedicated GitHub Actions secret with a $5 monthly
  limit and an appropriate model allowlist.

Never record an example or real provider key. The worker also consumes the
standard `GITHUB_EVENT_PATH`, `GITHUB_REPOSITORY`, `GITHUB_API_URL`, and the
workflow-scoped `GITHUB_TOKEN`.

### Enabling the advisory workflow

Merging `.github/workflows/pr-ai-review.yml` deploys the worker; GitHub creates
and destroys an `ubuntu-24.04` runner for each eligible event. No separate
service is deployed. Before enabling canaries:

1. Confirm GitHub Actions is enabled for the repository. Keep the repository's
   default `GITHUB_TOKEN` permission restricted; this workflow grants only
   `contents: read` and `pull-requests: write`, which is sufficient for its
   marked pull request timeline comment.
2. Set the `OPENROUTER_MODEL` repository variable to an explicit model slug
   that supports strict structured output and the configured provider policy.
3. Add `OPENROUTER_API_KEY` as a dedicated Actions secret. Give the key only
   the required model allowlist and a $5 monthly limit.
4. Confirm the selected provider route supports required parameters, zero data
   retention, and denied data collection.

Keep only non-secret rollout evidence: configuration date, model slug, provider
compatibility/privacy confirmation, canary PR and Actions run URLs, and the
observed result. Never record the key, authorization headers, account details,
or raw request/response bodies.

The GitHub resource inventory is deliberately small: one unprivileged quality
workflow, one trusted-base AI workflow, the built-in workflow-scoped
`GITHUB_TOKEN`, one repository variable, one repository secret, the standard
Actions event file and repository/API environment values, and one marked bot
timeline comment. The AI workflow checks out only the event's base SHA with
persisted credentials disabled. It does not execute PR-head code, application
tests, PR dependency files, generated shell, or model-proposed commands.

For rollout, use a public, same-repository, non-draft canary containing inert
shell text, prompt-injection text, hostile Markdown/control characters, binary
content, oversized text, and non-secret sentinel bait. Confirm the run reviews
the exact head SHA, reports model and omission counts, leaks no sentinel, and
updates the same marked comment on rerun. Exercise invalid-key, rate-limit,
timeout, malformed-response, and unavailable-model paths; each must publish
only a safe unavailable notice, fail the advisory check, and leave the quality
workflow independent. Also verify private, fork, and draft pull requests skip
the AI job while deterministic CI remains available.

To roll back, disable or remove only `.github/workflows/pr-ai-review.yml`, or
remove `OPENROUTER_API_KEY`. Provider calls and new comments then stop while
`.github/workflows/pr-quality.yml` remains active. If branch protection is ever
changed outside this rollout, remove any AI requirement separately; this
workflow is advisory and must not be required by this change. A marked bot
comment may be removed manually without editing human or unmarked comments.

Railway receives only `DATABASE_URL`; do not configure `TEST_DATABASE_URL` as a
Railway production variable.

## Developer Onboarding

The onboarding flow is JSON-first. Start the service with a PostgreSQL
`DATABASE_URL` and these environment variables:

```powershell
$env:APP_URL = "http://localhost:8000"
$env:GITHUB_OAUTH_CLIENT_ID = "your-github-oauth-client-id"
$env:GITHUB_OAUTH_CLIENT_SECRET = "your-github-oauth-client-secret"
$env:TOKEN_HASH_SALT = "a-long-random-secret"
uv run alembic upgrade head
uv run uvicorn main:app --reload
```

Configure the GitHub OAuth application's callback URL as
`<APP_URL>/auth/callback`. Never commit, print, or reuse the OAuth client
secret, token hash salt, API tokens, OAuth state, onboarding credentials, or
issuance credentials. Do not put them in shell history, logs, or source
control.

Use the supported local onboarding command rather than manually replaying REST
requests. Synchronize the environment first, then provide an HTTPS API origin;
HTTP is permitted only for `localhost`, `127.0.0.1`, or `::1` development
origins.

```powershell
uv sync
uv run azlimits-onboard --api-base-url http://localhost:8000 --token-name local-mcp
```

The command opens the existing browser OAuth login. After consent, the browser
callback still presents an onboarding credential; copy it deliberately into the
command's **hidden** prompt. Read the displayed EULA and type `yes` only to
accept it. Then provide a non-empty token name when prompted. If EULA acceptance
or token creation fails or is interrupted, restart onboarding rather than
retrying: either short-lived single-use credential may already be consumed.

After naming the token, the command requires a second confirmation: type
`reveal` only after reading the warning. Token creation proceeds only when both
the confirmation input and the dedicated reveal output are interactive TTYs.
The raw API token is displayed exactly once on that terminal; enter it
immediately into an approved MCP-host hidden secret prompt/store. Terminal
scrollback, recordings, remote sessions, and screen sharing are user-managed
exposure risks.

Do not place the token in command arguments, shell history, tool calls, logs,
committed files, `.env` files, generated scripts, registry values, workspace
configuration, or normal terminal input. If the reveal is declined, cancelled,
or cannot use interactive terminal input and output, no token is issued. If
the reveal stream fails after issuance, do not retry: the raw token cannot be
recovered, so restart onboarding to create a new token. The browser callback
credential, OAuth state, issuance credential, and API token are all short-lived
or sensitive and must never be logged or committed.

To expire a token, retain a different active token for the same user and call
`POST /auth/tokens/<token id>/expire` with that actor token's Bearer header. A
token owned by another user is reported as not found.

OpenAPI at `/docs` is the source of truth for typed request and response
payloads. OAuth state, onboarding credentials, and issuance credentials are
short-lived and single-use; repeat the prior step when one has expired or was
consumed.

## MCP Tool Setup

Complete developer onboarding with `azlimits-onboard` first. The local MCP
process needs only these settings:

- `AZLIMITS_API_BASE_URL` — the base URL of the running AzLimits API, such as
	`https://azlimits.example.com`.
- `AZLIMITS_API_TOKEN` — the raw API token retrieved from the approved secret
	store.

For VS Code, add this illustrative configuration to the **user-level** MCP
configuration, replacing only the repository-directory placeholder. When VS
Code prompts for `azlimits-api-token`, enter the one-time token directly in its
hidden secret prompt. The template deliberately contains an input reference,
not a token value:

```json
{
	"inputs": [
		{
			"id": "azlimits-api-token",
			"type": "promptString",
			"description": "AzLimits API token",
			"password": true
		}
	],
	"servers": {
		"azlimits": {
			"type": "stdio",
			"command": "uv",
			"args": ["run", "python", "mcp_server.py"],
			"cwd": "<repository-directory>",
			"env": {
				"AZLIMITS_API_BASE_URL": "https://azlimits.example.com",
				"AZLIMITS_API_TOKEN": "${input:azlimits-api-token}"
			}
		}
	}
}
```

For another MCP host, register `uv run python mcp_server.py` as a local
**stdio** server and pass only `AZLIMITS_API_BASE_URL` and
`AZLIMITS_API_TOKEN` to its child process through that host's approved secret
mechanism. Interactive secret inputs are not universal across MCP hosts. Do not
put this configuration in a source-controlled workspace file. The standalone
CLI cannot configure an already-running PowerShell, VS Code, or other parent
process.

The server is a separate local process: it does not require `DATABASE_URL`,
OAuth application credentials, or a database connection. Its supported tool is
`search_limitations(q, region?, sku?)`, which returns the REST support-status
verdict and complete source-backed records. An empty result does not prove that
no limitation exists.

The tool has no token argument. Never commit, print, paste into a tool call, or
place the API token in shell history or logs. The server reports only safe,
stable failure classes; when onboarding fails safely, restart rather than
replaying a potentially consumed state-changing request:

- `azlimits_configuration_error` — provide valid MCP API URL and token
	settings.
- `azlimits_authentication_error` — check that the configured API token is
	current and valid.
- `azlimits_license_error` — check that the token owner has an active Demo
	license.
- `azlimits_upstream_unavailable` — retry after the AzLimits API is available.

## Azure Limitations Skill

Once the MCP tool is configured, coding agents load the `azlimits` skill
automatically when they generate, modify, review, or approve production Azure
architecture or infrastructure-as-code. The skill directs the agent to search
limitations per service before the design is finalized, to keep each record's
source provenance intact, and to treat an empty result or a tool failure as
inconclusive rather than as approval.

The skill is maintained once, at `.agents/skills/azlimits/SKILL.md`. Every
client path is a repository-relative symlink to that same directory:

- `.github/skills/azlimits` — GitHub Copilot
- `.codex/skills/azlimits` — Codex
- `.claude/skills/azlimits` — Claude

Edit only the canonical file. The aliases are symlinks, not copies, so a change
made through any path lands in the same file, and
`tests/test_azlimits_skill.py` fails if an alias becomes a copy, a broken link,
or resolves somewhere else.

The checkout must preserve real symlinks. On Windows that needs
`core.symlinks=true` together with Developer Mode or the
SeCreateSymbolicLinkPrivilege. If an alias materializes as an ordinary file
containing a path, re-enable symlinks and re-check out that path instead of
replacing it with a copied directory.

The skill is for production use after onboarding and MCP configuration are
complete; see [MCP Tool Setup](#mcp-tool-setup). It carries no setup, token, or
repository-development instructions, and it never asks a user for a token.

## Verification

Use a disposable PostgreSQL database for `TEST_DATABASE_URL`, distinct from
`DATABASE_URL` and never configured on a production Railway service.

```powershell
$env:TEST_DATABASE_URL = "postgresql://..."
uv sync --locked --group dev
uv run ruff check .
uv run mypy .
uv run pytest tests/ -v --cov --cov-branch --cov-report=term-missing
```
