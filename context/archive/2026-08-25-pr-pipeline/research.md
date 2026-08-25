---
date: 2026-08-25T10:53:31+02:00
researcher: Codex
git_commit: 8b726c1428ed922493afb2020320322c8965b963
branch: main
repository: azure-oracle
topic: "AI-powered GitHub pull request review pipeline using OpenRouter"
tags: [research, codebase, github-actions, openrouter, pull-request-review, security]
status: complete
last_updated: 2026-08-25
last_updated_by: Codex
---

# Research: AI-powered GitHub pull request review pipeline using OpenRouter

**Date**: 2026-08-25T10:53:31+02:00
**Researcher**: Codex
**Git Commit**: 8b726c1428ed922493afb2020320322c8965b963
**Branch**: main
**Repository**: azure-oracle

## Research Question

How should this repository add a GitHub Actions pipeline that runs when a pull
request is opened, uses an AI agent through the OpenRouter API to review the
submitted changes for code quality and security, and prepares a summary for a
human reviewer?

## Summary

This is greenfield CI work. The repository selects GitHub Actions as its CI
provider, but it has no tracked workflow or OpenRouter integration. The local
`.github/` tree is ignored course/tooling material; a workflow added there will
not be committed until `.gitignore` receives narrow tracking exceptions.

The safest design is a data-only reviewer:

1. Trigger a trusted default-branch workflow with `pull_request_target` and
   `types: [opened]`.
2. Never check out, install, import, or execute code from the pull request.
3. Fetch the PR diff through the GitHub API, bound and sanitize it, and treat the
   title, body, branch names, diff, and model output as untrusted data.
4. Run a small, testable Python reviewer from the trusted base revision. It can
   use the repository's existing Python 3.12, `httpx`, Pydantic, pytest, and
   `respx` stack rather than introducing Node solely for this feature.
5. Call OpenRouter with a dedicated budget-limited secret, an explicit model,
   privacy/provider restrictions, bounded input/output, timeout, and strict
   structured output.
6. Render one informational PR comment for a human reviewer. Do not approve,
   merge, edit code, push commits, or make the model verdict a merge gate in the
   initial slice.

`pull_request_target` is privileged and is safe here only under the hard rule
that PR-head code is never checked out or executed. If fork support is explicitly
out of scope, a plain `pull_request` workflow with a same-repository guard is a
simpler alternative, but fork runs will not receive the OpenRouter secret and
their `GITHUB_TOKEN` is read-only.

## Detailed Findings

### Repository and CI integration surface

- GitHub Actions is the selected CI provider, while the recorded default flow
  concerns deployment after merge, not PR review
  ([tech-stack.md:9-10](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/context/foundation/tech-stack.md#L9-L10)).
- There are no tracked `.github/**` files and no workflow history. The local
  `.github/` material is ignored by `.gitignore`; implementation must add narrow
  exceptions for the exact workflow, trusted script, and prompt/rubric files it
  intends to commit. Force-adding ignored files would hide this contract and is
  not recommended.
- Python is the native implementation surface: Python 3.12+, `httpx`, and
  Pydantic are runtime dependencies; pytest, Ruff, mypy, and `respx` are already
  development dependencies
  ([pyproject.toml:6-15](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/pyproject.toml#L6-L15),
  [pyproject.toml:28-42](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/pyproject.toml#L28-L42)).
  A custom Python client/parser is lower-friction and more testable here than a
  second Node-based agent toolchain.
- Existing deterministic commands are `uv run pytest tests/ -v`,
  `uv run ruff check .`, and `uv run mypy .`
  ([README.md:18-30](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/README.md#L18-L30)).
  The AI review should complement, not replace, those checks.
- DB-backed tests require a disposable PostgreSQL database and
  `TEST_DATABASE_URL`; they must never reuse production `DATABASE_URL`
  ([README.md:20-33](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/README.md#L20-L33)).
  Running the application test suite is a separate unprivileged CI concern, not
  something the secret-bearing AI-review job should do against PR code.
- `AGENTS.md:27` is stale when it says no linter or test suite exists. Live
  configuration and the README show otherwise; it remains correct that no
  GitHub Actions workflow is tracked.

### Review policy must be repository-specific

Generic style advice is insufficient. The review prompt should load and
prioritize these current invariants:

- Every public limitation record needs its source URL, quote/excerpt,
  confidence, and verification state.
- Raw API tokens, OAuth credentials, and other secrets must never be logged,
  returned, committed, or hard-coded.
- Token validity and active Demo license state must be checked before protected
  limitation data is returned.
- The MVP remains API/MCP-first and excludes dashboards, automatic IaC
  remediation, other clouds, and advanced billing.

These rules are explicit in
[AGENTS.md:5-10](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/AGENTS.md#L5-L10)
and the product guardrails
([prd.md:67-72](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/context/foundation/prd.md#L67-L72)).
The test strategy already names missing provenance, unverified data exposure,
auth/license bypass, and secret leakage as its top risks
([test-plan.md:43-46](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/context/foundation/test-plan.md#L43-L46)).

The human-facing output should contain:

- reviewed PR head SHA and actual OpenRouter model;
- reviewed file/byte counts plus any omitted, binary, or truncated content;
- concise change summary;
- prioritized findings with severity, path, line when available, evidence, and
  recommendation;
- missing or risky tests and explicit uncertainty;
- an AI-generated, advisory-only disclaimer.

### GitHub Actions event and permissions

GitHub documents `pull_request_target` as running in the base repository's
trusted context and warns against checking out or running untrusted PR code in
that event. It is appropriate only for this data-only design
([GitHub event documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request_target),
[secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use#mitigating-the-risks-of-untrusted-code-checkout)).

Recommended workflow controls:

- `pull_request_target: { types: [opened] }` to match the stated trigger.
- Explicit permissions only: `contents: read` when a trusted base checkout is
  needed and `pull-requests: write` to read the diff and post the summary. All
  unrelated permissions remain `none`
  ([workflow permission syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#defining-access-for-the-github_token-scopes)).
- Fetch the unified diff through GitHub's pull-request API, or paginate the
  files endpoint, rather than checking out PR head
  ([get pull request](https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request),
  [list pull-request files](https://docs.github.com/en/rest/pulls/pulls#list-pull-requests-files)).
- If trusted repository files are needed, check out the base SHA explicitly,
  set `persist-credentials: false`, and pin `actions/checkout` to a full commit
  SHA. GitHub identifies a full action commit SHA as the only immutable action
  reference
  ([third-party action guidance](https://docs.github.com/en/actions/reference/security/secure-use#using-third-party-actions)).
- Add concurrency keyed by PR number and make repeat posting idempotent with a
  stable hidden comment marker.
- Put dynamic GitHub context values in environment variables or JSON/files;
  never interpolate untrusted PR fields directly into shell source
  ([script-injection guidance](https://docs.github.com/en/actions/concepts/security/script-injections)).

An `opened`-only trigger deliberately becomes stale after later commits. Adding
`synchronize` and `reopened` is a sensible follow-up, but changes the stated MVP
and requires reliable update/deduplication behavior.

### OpenRouter API and model boundary

- Store `OPENROUTER_API_KEY` only as a GitHub Actions secret and expose it only
  to the API-call step. Use a dedicated key with a budget cap and model/provider
  allowlists. Secret redaction is defense in depth, not a security boundary.
- Store the reviewed model slug in a non-secret variable such as
  `OPENROUTER_MODEL`. Prefer an explicit, reviewed model/version over
  `openrouter/auto`, free routing, or a moving latest alias when reproducibility
  matters. Verify required features through model metadata
  ([OpenRouter models guide](https://openrouter.ai/docs/guides/overview/models)).
- Send a non-streaming `POST https://openrouter.ai/api/v1/chat/completions`
  request with Bearer authorization, JSON content, explicit model, bounded
  output, and a timeout; validate the HTTP status and
  `choices[0].message.content`
  ([chat-completion API](https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request)).
- Require strict JSON Schema output where the selected model supports it, set
  `provider.require_parameters: true`, then validate locally before rendering
  Markdown
  ([structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs)).
- Enforce privacy/provider controls appropriate for private source code, such as
  zero-data-retention routing and denial of data-collecting providers, subject to
  model availability
  ([ZDR](https://openrouter.ai/docs/guides/features/zdr),
  [provider selection](https://openrouter.ai/docs/guides/routing/provider-selection),
  [data collection](https://openrouter.ai/docs/guides/privacy/data-collection)).
- Bound diff bytes, files, output tokens, retries, and wall-clock time. Retry
  only transient failures with a small bounded policy. Never log the raw request,
  raw provider response, authorization header, or secret-bearing environment.

The PR diff, metadata, and comments can contain prompt-injection instructions.
They must be delimited as data; the system prompt must forbid obeying repository
content, using tools, revealing credentials, or performing actions. The model
should receive no shell, GitHub, filesystem, or function-calling tools. OpenRouter
prompt-injection guardrails may be an additional signal, but OpenRouter explicitly
describes detection as imperfect
([prompt-injection guardrail](https://openrouter.ai/docs/guides/features/guardrails/prompt-injection)).

### Verification strategy

Focused automated tests should cover:

- OpenRouter request shape without containing the API key;
- exact model/provider/privacy/limit configuration;
- strict structured-output parsing and Markdown rendering;
- malformed, empty, oversized, and unexpected model responses;
- timeouts, rate limits, authentication/payment failures, and bounded retry;
- diff file/byte limits, binary and empty diffs, and visible truncation notices;
- prompt-injection strings treated as inert content;
- Markdown/control-character sanitization;
- stable comment marker and rerun update behavior;
- workflow trigger and least-privilege permission assertions;
- absence of checkout or execution of PR-head content;
- safe error messages and sentinel-secret absence from logs/output.

Manual verification must be explicit:

1. Configure `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`, confirm the dedicated
   key's budget, model access, and privacy/provider guardrails.
2. Confirm repository Actions settings permit the workflow's PR comment and
   that no broader default workflow permissions are relied on.
3. Open a same-repository PR and a fork-style PR containing malicious shell text,
   workflow changes, prompt instructions, Markdown, and secret-exfiltration bait.
4. Confirm no PR-head checkout or execution occurs, the secret never appears in
   logs/comments, and the comment identifies the exact reviewed head SHA.
5. Exercise empty, binary, oversized, and truncated diffs; OpenRouter timeout,
   rate limit, invalid key, malformed response, and unavailable-model paths.
6. Re-run the workflow and confirm it updates or replaces its own marked comment
   without deleting human comments or producing duplicates.

## Code References

- `context/changes/pr-pipeline/change.md:12-16` - Requested trigger, provider,
  review purpose, and quality/security focus (uncommitted change artifact).
- [`.gitignore:26-29`](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/.gitignore#L26-L29) - Blanket ignore covering `.github/`.
- [`AGENTS.md:5-10`](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/AGENTS.md#L5-L10) - Product invariants the reviewer must enforce.
- [`pyproject.toml:6-15`](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/pyproject.toml#L6-L15) - Python and runtime dependencies.
- [`pyproject.toml:28-42`](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/pyproject.toml#L28-L42) - Existing test, lint, typing, and HTTP-mocking tools.
- [`tests/conftest.py:15-57`](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/tests/conftest.py#L15-L57) - Isolated PostgreSQL test fixture and migrations.
- [`lefthook.yml:1-9`](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/lefthook.yml#L1-L9) - Existing local Ruff/mypy gates.
- [`context/foundation/test-plan.md:122-135`](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/context/foundation/test-plan.md#L122-L135) - Required CI quality gates.
- [`main.py:188-442`](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/main.py#L188-L442) - Main FastAPI endpoint surface.
- [`auth.py:31-70`](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/auth.py#L31-L70) - Authentication/license boundary.
- [`logging_middleware.py:8-84`](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/logging_middleware.py#L8-L84) - Secret-scrubbing and error path.
- [`mcp_server.py:42-182`](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/mcp_server.py#L42-L182) - MCP boundary and safe upstream failures.

## Architecture Insights

The pipeline has three trust zones:

1. **Trusted orchestration** - default-branch workflow, pinned actions, trusted
   Python reviewer/prompt, explicit permissions, secrets.
2. **Untrusted review input** - PR metadata and bounded diff fetched as data.
3. **Untrusted provider output** - schema-validated AI response rendered into an
   informational GitHub comment.

No executable path should cross from zones 2 or 3 into zone 1. In particular,
the workflow must not execute PR scripts, tests, package installation, generated
shell, model-proposed commands, or model tool calls. Deterministic CI and the AI
review should be separate jobs/workflows with different trust and permission
profiles.

The reviewer should separate portable policy from provider mechanics: a tracked
rubric/prompt defines AzLimits-specific review criteria and a small Python module
owns GitHub/OpenRouter transport, limits, validation, rendering, and errors. This
makes model replacement possible without rewriting review policy.

## Historical Context (from prior changes)

- Archived observability work requires secret-leak coverage on success and
  failure paths, including header and traceback redaction
  ([plan.md:43](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/context/archive/2026-08-02-observability-logging-floor/plan.md#L43),
  [plan.md:220](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/context/archive/2026-08-02-observability-logging-floor/plan.md#L220)).
- Archived implementation reviews found missing failure matrices, unbounded
  upstream responses, and incomplete secret-exposure assertions. These are
  directly relevant priors for timeout, size, retry, redaction, and failure-path
  tests in the OpenRouter client.
- Local ignored 10x course material includes an Anthropic-specific
  `.github/skills/10x-impl-review-ci/` workflow and a provider-neutral review
  rubric. It is useful design evidence but is not tracked repository contract.
  Reuse the rubric deliberately; do not copy the Claude action, branch-writing,
  inline-comment, status-gating, or Node setup mechanics into this smaller
  OpenRouter slice.
- Human merge authority is consistent with the requested outcome: prepare a
  summary for a reviewer. Existing review history does not justify automatic
  approval, code changes, merge, or deployment.

## Related Research

- [`context/archive/2026-08-02-observability-logging-floor/research.md`](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/context/archive/2026-08-02-observability-logging-floor/research.md) - Logging and secret-safety foundations.
- [`context/archive/2026-08-16-mcp-tool-wrapper/research.md`](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/context/archive/2026-08-16-mcp-tool-wrapper/research.md) - Bounded HTTP/provider error handling patterns.
- [`context/archive/2026-08-06-developer-onboarding-token/research.md`](https://github.com/patryk-plonka/azure-oracle/blob/8b726c1428ed922493afb2020320322c8965b963/context/archive/2026-08-06-developer-onboarding-token/research.md) - Secret handoff and safe failure semantics.

## Open Questions

1. Which explicit OpenRouter model slug, maximum per-review token budget, and
   monthly key budget should be the default?
2. Is sending private PR diffs to OpenRouter and its selected downstream
   zero-data-retention provider approved for this repository?
3. Should draft PRs be reviewed when opened, skipped until `ready_for_review`, or
   reviewed only on an explicit label?
4. Is opened-only behavior intentional despite becoming stale after later
   commits, or should `synchronize`/`reopened` be included now?
5. On provider failure, should the workflow post a deterministic operational
   notice, fail silently with an Actions error, or do both?
6. Should fork PRs be supported by the recommended data-only
   `pull_request_target` design, or can the initial scope use `pull_request` and
   skip forks?
