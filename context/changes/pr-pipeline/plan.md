# Pull Request Quality and AI Review Worker Pipeline Implementation Plan

## Overview

Add a lightweight, reviewer-visible pull request evidence baseline and a
secondary OpenRouter review summary produced by a one-shot Python worker.
Deterministic CI will prove that lint,
typing, tests, and a measured coverage floor pass; the AI layer will provide
advisory semantic, security, and missing-test triage without executing pull
request code in a secret-bearing context.

## Current State Analysis

Opening a pull request produces no shared CI evidence or review summary.
Review completeness therefore depends on the reviewer remembering and running
the right local commands.

The repository already has pytest, Ruff, mypy, httpx, Pydantic, and respx, but
has no tracked GitHub Actions workflow and no coverage dependency or policy.
Local pre-commit automation runs both Ruff and mypy, so the live configuration
is more complete than the original Ruff-only observation, but tests and
coverage remain absent from the PR path.

The full test suite is PostgreSQL-backed and cannot currently run from a clean
checkout: `tests/test_seed_import.py` reads
`concept/azure_limitations_db.csv`, while the blanket `concept/` ignore rule
keeps that required seed file untracked. The blanket `.github/` ignore rule
similarly prevents new workflow files from being committed.

The frame investigation established the following:

| Hypothesis | Evidence strength | Planning consequence |
| --- | --- | --- |
| Missing deterministic evidence is the main source of inconsistency | Strong | Build the quality gate first and make it authoritative. |
| Context assembly is the main source of toil | Weak | Let AI summarize context, but keep the outcome advisory. |
| Absence of an AI summary is the main problem | Weak | Do not use the model to prove health or decide mergeability. |
| Opened-only feedback creates current freshness toil | None | Keep the initial AI event scope to opened/ready PRs. |

## Desired End State

Every eligible pull request receives a deterministic GitHub check showing
Ruff, mypy, the complete PostgreSQL-backed pytest suite, and an enforced
line/branch coverage baseline. The baseline is measured from the reproducible
suite, rounded down to a whole-number threshold, recorded in configuration,
and fails subsequent regressions.

Public, same-repository, non-draft pull requests additionally receive one
clearly marked AI review comment. The comment identifies the reviewed head SHA
and actual model, summarizes the change, prioritizes evidence-backed quality,
security, and test-gap findings, and discloses omitted or truncated input. It
is advisory only: humans retain merge authority and the AI check is not a
required branch-protection gate.

The reviewer is visibly a one-shot worker rather than an autonomous agent: a
PR event starts a fresh GitHub-hosted runner, trusted `pr_review.py` performs a
bounded request/validate/publish cycle, and the runner is destroyed when the
job finishes. There is no separately deployed application to keep online.

### Key Discoveries

- `.github/` and `concept/` are blanket-ignored, so narrow exceptions are
  required for the workflows, rubric, and seed input (`.gitignore:26-29`).
- Ruff, mypy, pytest, httpx, Pydantic, and respx are already native to the
  project; only coverage and optional workflow parsing support need adding
  (`pyproject.toml:6-15,28-42`).
- The complete suite requires an isolated PostgreSQL database and applies
  migrations before tests (`tests/conftest.py:15-57`).
- Seed-import tests depend on the real 93+ record corpus and also downgrade the
  disposable database to `base`; they must not share a production database or
  run concurrently against one database (`tests/test_seed_import.py:13-95`,
  `seed.py:15-76`).
- The product's highest risks are provenance loss, unverified data exposure,
  auth/license bypass, and secret leakage; the AI rubric must prioritize those
  rules rather than generic style advice (`AGENTS.md:5-10`,
  `context/foundation/test-plan.md:35-49`).
- Secret-bearing AI orchestration and executable PR tests require separate
  trust profiles (`context/changes/pr-pipeline/research.md`, Architecture
  Insights).
- The AI component needs no agent framework or provider SDK: the selected
  implementation is a root-level Python 3.12 worker using the existing
  `httpx` and Pydantic dependencies to call GitHub REST and OpenRouter REST
  directly (`context/changes/pr-pipeline/frame.md`, Follow-up Frame).
- GitHub Actions is both the control plane and deployment target. Each run gets
  a fresh GitHub-hosted VM, the built-in `GITHUB_TOKEN`, repository
  configuration, and the event payload; no persistent bot service is operated.

## What We're NOT Doing

- Automatically approving, rejecting, merging, editing, or pushing to pull
  requests.
- Making the model verdict a required merge gate.
- Reviewing private-repository code with OpenRouter.
- Running AI review for fork pull requests or draft pull requests.
- Checking out, installing, importing, or executing PR-head code in the
  secret-bearing AI workflow.
- Adding inline review comments, code suggestions, tool calls, or autonomous
  remediation.
- Adding changed-lines coverage, a universal 80% threshold, or broad test
  remediation beyond what is needed to establish the measured baseline.
- Adding `synchronize` or `reopened` AI events in the initial rollout.
- Tracking the existing ignored `.github/` course/tooling content or the whole
  `concept/` directory.
- Introducing an OpenRouter SDK, GitHub SDK, agent framework, GitHub App,
  webhook receiver, container image, queue, persistent database, or always-on
  review service.

## Implementation Approach

Use two independent GitHub workflows. The unprivileged quality workflow may
execute PR code against a disposable PostgreSQL service and has no secrets or
write permissions. The privileged AI workflow runs trusted base-branch code,
fetches the PR diff through the GitHub API as bounded untrusted data, calls
OpenRouter through a small typed Python module, validates structured output,
and upserts one informational PR comment.

Both workflows use GitHub-hosted `ubuntu-24.04` runners. External actions are
immutable: `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1`
(`v7.0.1`) and
`astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9`
(`v9.0.0`), with the latter installing `uv` `0.12.1`. Python 3.12 is installed
through `uv`, so no additional Python setup action or SDK layer is required.

Coverage follows the selected baseline-ratchet policy. The implementation first
makes the full suite reproducible, measures application line and branch
coverage, rounds the observed percentage down to a whole number, records that
threshold in `pyproject.toml`, and verifies the same command fails below it.

The AI job is guarded to public repositories, same-repository branches, and
ready PRs. It uses a dedicated `OPENROUTER_API_KEY` with a $5 monthly limit and
an explicit structured-output-capable model slug supplied through the
`OPENROUTER_MODEL` repository variable. Per-request provider policy requires
parameter support, zero data retention, and denial of data-collecting routes.

### End-to-end runtime

```text
pull_request_target event
        |
        v
ephemeral ubuntu-24.04 GitHub-hosted runner
        |
        +-- trusted base checkout + rubric + pr_review.py
        +-- GITHUB_EVENT_PATH + built-in GITHUB_TOKEN
        +-- OPENROUTER_MODEL variable + OPENROUTER_API_KEY secret
        |
        v
GitHub REST -> bounded PR metadata/files -> OpenRouter REST
        |                                      |
        +---------- Pydantic validation <------+
                           |
                           v
             create/update one PR timeline comment
                           |
                           v
                    runner is destroyed
```

### Runtime and GitHub resource inventory

| Resource | Concrete contract |
| --- | --- |
| Deterministic workflow | `.github/workflows/pr-quality.yml`; unprivileged `pull_request` events; no secrets or writes. |
| AI workflow | `.github/workflows/pr-ai-review.yml`; trusted `pull_request_target` events; data-only handling of PR content. |
| Runtime | Fresh GitHub-hosted `ubuntu-24.04` VM per job; no self-hosted runner or external deployment. |
| Executable | `uv run python pr_review.py`; custom Python 3.12 worker using `httpx` and Pydantic directly. |
| GitHub identity | Workflow-scoped built-in `GITHUB_TOKEN`; no PAT, deploy key, or GitHub App installation. |
| GitHub permissions | Quality: `contents: read`; AI: `contents: read`, `pull-requests: write`; all unspecified scopes are `none`. |
| Event input | Standard `GITHUB_EVENT_PATH`, `GITHUB_REPOSITORY`, and `GITHUB_API_URL`; the worker reads PR number and head/base SHAs from the event JSON. |
| Provider config | Repository variable `OPENROUTER_MODEL` and dedicated repository secret `OPENROUTER_API_KEY` with a $5 monthly cap. |
| Review policy | `.github/pr-ai-review-rubric.md`, read only from the trusted base checkout. |
| Durable output | One marked `github-actions[bot]` PR timeline comment; no database or artifact is required. |

The worker authenticates to GitHub REST with `Authorization: Bearer
<GITHUB_TOKEN>`, `Accept: application/vnd.github+json`, and
`X-GitHub-Api-Version: 2022-11-28`. Its only GitHub API bindings are:

- `GET /repos/{owner}/{repo}/pulls/{pull_number}` for authoritative PR metadata;
- paginated `GET /repos/{owner}/{repo}/pulls/{pull_number}/files` for patches;
- paginated `GET /repos/{owner}/{repo}/issues/{issue_number}/comments` to find
  the marked bot comment;
- `POST /repos/{owner}/{repo}/issues/{issue_number}/comments` to create it; and
- `PATCH /repos/{owner}/{repo}/issues/comments/{comment_id}` to update it.

The only non-GitHub API binding is non-streaming `POST
https://openrouter.ai/api/v1/chat/completions`. Neither token may appear in the
other service's request, logs, exceptions, or rendered output.

## Critical Implementation Details

### Trust boundary

The AI workflow may use `pull_request_target` only because it never executes PR
content. It must explicitly check out the base SHA with persisted credentials
disabled, fetch changed content through the API, and treat titles, bodies,
branch names, filenames, patches, and model output as untrusted data. A
same-repository guard limits spend but does not weaken this rule.

### Coverage baseline ordering

Do not choose or record the coverage threshold until the seed corpus is tracked
and the entire suite passes in a clean environment. Otherwise the baseline
would describe a partial or irreproducible test run.

### Failure visibility

Provider, configuration, parsing, or comment-publication failures must expose
only a safe category. The workflow upserts a deterministic “AI review
unavailable; human review required” notice when possible and fails its
non-required check so outages are visible without blocking merge policy.

## Phase 1: Reproducible Deterministic Quality Gate

### Overview

Make the existing test contract runnable from a clean checkout, establish the
coverage ratchet, and add the authoritative no-secret PR workflow.

### Changes Required:

#### 1. Track only required ignored assets

**File**: `.gitignore`

**Intent**: Preserve the blanket ignores for local course and research material
while allowing the exact CI assets and production seed corpus required by the
tracked test suite.

**Contract**: Narrow exceptions make
`concept/azure_limitations_db.csv`, `.github/workflows/pr-quality.yml`,
`.github/workflows/pr-ai-review.yml`, and `.github/pr-ai-review-rubric.md`
trackable. Existing unrelated `.github/**` and `concept/**` content remains
ignored.

#### 2. Commit the reproducible seed input

**File**: `concept/azure_limitations_db.csv`

**Intent**: Make the existing import/provenance tests and documented seed
operation reproducible from a clean checkout.

**Contract**: Track the current source-backed corpus without dropping or
rewriting its source URL, quote, confidence, or verification-related input
fields. The file continues to satisfy `seed.py`'s schema and minimum-record
contract.

#### 3. Add coverage tooling and policy

**File**: `pyproject.toml`

**Intent**: Add pytest coverage support and centralize which application code is
measured, branch measurement, report behavior, and the measured baseline floor.

**Contract**: The dev dependency group includes `pytest-cov` and a YAML parser
only if the workflow contract test uses one. Coverage measures production root
modules, excludes tests, migrations, caches, and generated artifacts, reports
missing lines, measures branches, and records the rounded-down baseline as
`fail_under` after a complete green run.

**File**: `uv.lock`

**Intent**: Lock the new development dependencies through the repository's
normal `uv` workflow.

**Contract**: `uv sync --locked --group dev` succeeds on Python 3.12 without
mutating the lockfile.

#### 4. Add the unprivileged PR quality workflow

**File**: `.github/workflows/pr-quality.yml`

**Intent**: Provide reviewer-visible deterministic evidence whenever an
eligible PR is opened or becomes ready for review.

**Contract**: A `pull_request` workflow for `opened` and `ready_for_review`
events uses an `ubuntu-24.04` GitHub-hosted runner, explicit `contents: read`
permissions,
`actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1`, and
`astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9`
configured for `uv` `0.12.1`. It installs Python 3.12 through `uv`, uses locked
dependencies, and receives no repository or provider secrets. It runs Ruff and
mypy plus the full pytest suite against a
health-checked disposable PostgreSQL 16 service exposed only as
`TEST_DATABASE_URL`. Database tests are not parallelized against the same
service. The coverage result and missing-line summary are visible in the job
output or job summary.

#### 5. Test the deterministic workflow contract

**File**: `tests/test_pr_workflows.py`

**Intent**: Prevent later workflow edits from silently broadening permissions,
losing deterministic checks, using a production database, or crossing the AI
trust boundary.

**Contract**: Structural tests assert the quality workflow's event types,
permissions, immutable action references, canonical commands, isolated
`TEST_DATABASE_URL`, PostgreSQL health check, and absence of OpenRouter secrets.
They also assert that only intended ignored paths become trackable.

#### 6. Document local parity and baseline maintenance

**File**: `README.md`

**Intent**: Give contributors the exact local commands corresponding to CI and
explain how the coverage floor is updated deliberately.

**Contract**: The Tests/Verification documentation names the disposable
PostgreSQL requirement, locked sync, Ruff, mypy, full pytest-with-coverage
command, current threshold source, and rule that a lower baseline requires an
explicit reviewed policy change.

### Success Criteria:

#### Automated Verification:

- Ignored-path contract passes: `uv run pytest tests/test_pr_workflows.py -v`
- Locked dependencies install: `uv sync --locked --group dev`
- Lint passes: `uv run ruff check .`
- Type checking passes: `uv run mypy .`
- Full PostgreSQL suite passes with configured line/branch coverage and the
  recorded baseline: `uv run pytest tests/ -v --cov --cov-branch --cov-report=term-missing`
- Clean-checkout simulation confirms the tracked seed and quality workflow are
  present through `git ls-files` and no unrelated ignored `.github/` or
  `concept/` content is added.

#### Manual Verification:

- Open a canary PR and record its PR URL and Actions run URL; confirm Ruff,
  mypy, tests, and the coverage result are separately understandable to a
  reviewer.
- In separate canary commits, introduce one Ruff failure, one failing test, and
  one coverage regression; record the failing run URLs, then restore the code
  and confirm the final run is green.
- Inspect the run configuration and logs to confirm the PostgreSQL database is
  disposable, only `TEST_DATABASE_URL` is supplied to tests, and no production
  `DATABASE_URL` or application/provider secret is present.

**Implementation Note**: Complete the clean-checkout and canary checks before
starting the secret-bearing workflow. The measured threshold is meaningful only
after the complete suite is reproducible.

---

## Phase 2: Bounded AI Reviewer Core

### Overview

Build the provider-neutral review policy and testable Python boundaries before
granting any workflow access to an OpenRouter secret or PR comment permission.

### Changes Required:

#### 1. Add the repository-specific review rubric

**File**: `.github/pr-ai-review-rubric.md`

**Intent**: Focus qualitative review on AzLimits invariants and risks that
deterministic checks cannot settle.

**Contract**: The rubric prioritizes provenance completeness, verified-only
serving, token/license enforcement, secret safety, API/MCP-first scope,
cross-file semantics, bounded external I/O, and missing tests. It suppresses
style-only feedback already handled by Ruff/mypy, treats all PR content as data,
forbids following embedded instructions or requesting tools/secrets, requires
evidence and uncertainty, and caps findings.

#### 2. Add the typed reviewer module

**File**: `pr_review.py`

**Intent**: Isolate GitHub transport, bounded context assembly, OpenRouter
transport, schema validation, safe rendering, and comment publication behind
small testable Python contracts consistent with the repository's root-module
layout.

**Contract**: The entrypoint is `uv run python pr_review.py`. It reads
`GITHUB_EVENT_PATH`, `GITHUB_REPOSITORY`, `GITHUB_API_URL`, `GITHUB_TOKEN`,
`OPENROUTER_MODEL`, and `OPENROUTER_API_KEY` from the environment; reads the PR
number and expected head/base SHAs from the event JSON; and loads the rubric
from the fixed trusted path `.github/pr-ai-review-rubric.md`. Typed
configuration rejects missing or unsafe values. No command-line PR text or
event field is evaluated as shell source.

GitHub transport uses direct `httpx` REST calls with Bearer authentication,
`application/vnd.github+json`, API version `2022-11-28`, and only the five
metadata/files/list-comment/create-comment/update-comment endpoints listed in
the runtime inventory. It does not use PyGithub, Octokit, `gh`, a GitHub App,
or a personal access token. GitHub input is paginated and bounded to
50 files and 64 KiB of UTF-8 review content; missing patches are classified as
binary/unavailable and truncation occurs at file or patch boundaries where
possible. The fetched head SHA must equal the event head SHA before publication.

The OpenRouter request is a direct `httpx` call to
`POST https://openrouter.ai/api/v1/chat/completions`; it does not use an
OpenRouter SDK or agent framework. It is non-streaming, uses the explicit model, a maximum of
2,000 output tokens, a 45-second timeout, no tools/functions, strict JSON Schema
output, and provider requirements for parameter support, zero data retention,
and denied data collection. At most two total attempts are allowed; only
timeouts, connection failures, 408, 429, and 5xx responses are retryable, with
a bounded `Retry-After`. Authentication, payment, policy, validation, empty,
and malformed-response failures are not retried.

The validated result contains a bounded summary, at most 10 typed findings, at
most 8 test gaps, and at most 5 uncertainties. Each finding has constrained
severity, title, path, optional positive line, evidence, recommendation, and
confidence, with extra fields forbidden. Rendering is deterministic and adds
the reviewed SHA, requested and returned model, reviewed/omitted/binary/file and
byte counts, truncation notices, advisory disclaimer, and stable marker
`<!-- azlimits-ai-pr-review:v1 -->`.

Comment upsert selects only a `github-actions[bot]` comment carrying the exact
marker, updates the canonical marked comment on rerun, creates one when absent,
and never edits or deletes human/unmarked comments. Empty or entirely binary
diffs produce a deterministic incomplete-review notice without calling
OpenRouter. Logs, exceptions, comments, and return values never contain the
API key, raw authorization header, raw provider response, or raw request body.

#### 3. Add reviewer behavior and failure-matrix tests

**File**: `tests/test_pr_review.py`

**Intent**: Prove the security and reliability boundary without live GitHub or
OpenRouter effects.

**Contract**: pytest/respx tests cover the entrypoint/environment contract,
exact GitHub REST paths, headers, and pagination, exact OpenRouter request
configuration, strict schema parsing, deterministic rendering, file/byte limits, binary
and empty diffs, prompt-injection strings, malicious Markdown/control
characters, event/fetched SHA mismatch, and create-versus-update comment
behavior. The failure matrix covers connection errors, timeout, 408, 429 with
bounded delay, 5xx, 400/401/402/403, empty/malformed/oversized output,
unsupported model response, and comment API failure. Tests assert retry/no-retry
counts and prove a sentinel API key is absent from captured logs, exceptions,
requests bodies, and rendered comments.

#### 4. Keep module and operator documentation current

**File**: `README.md`

**Intent**: Document reviewer limits, advisory semantics, supported PR scope,
and safe configuration without exposing secret values.

**Contract**: Documentation names the component an AI PR review worker and
shows the event-to-runner-to-API-to-comment lifecycle. It states that GitHub
Actions is the deployment target and that no SDK/framework, GitHub App,
container, webhook service, or persistent infrastructure is operated.
Documentation names `OPENROUTER_MODEL` as an explicit repository
variable and `OPENROUTER_API_KEY` as a dedicated GitHub secret with a $5 monthly
limit, but contains no example key. It explains that private, fork, and draft
PRs are skipped; provider privacy controls are defense in depth; and provider
failures require human review.

### Success Criteria:

#### Automated Verification:

- Reviewer unit and HTTP-contract tests pass: `uv run pytest tests/test_pr_review.py -v`
- The complete suite remains green with the Phase 1 coverage floor:
  `uv run pytest tests/ -v --cov --cov-branch --cov-report=term-missing`
- Lint passes: `uv run ruff check .`
- Type checking passes: `uv run mypy .`
- Sentinel-secret assertions prove no credential appears in test-captured logs,
  exceptions, request JSON, or rendered comments.

#### Manual Verification:

- Review the rendered comment fixtures and confirm findings are concise,
  evidence-backed, repository-specific, explicitly uncertain when appropriate,
  and clearly advisory.
- Inspect the mocked request fixture and record the test name/output proving the
  exact model, strict schema, output limit, no-tools contract, ZDR,
  `data_collection: deny`, and `require_parameters: true` fields.
- Confirm the dedicated OpenRouter key has a $5 monthly cap and model allowlist,
  and record only the date and non-secret configuration confirmation—never the
  key or account details.

**Implementation Note**: Do not add or enable the secret-bearing workflow until
all provider, rendering, retry, and sentinel-secret tests pass.

---

## Phase 3: Advisory PR Publication

### Overview

Wire the trusted reviewer into GitHub Actions for the selected public,
same-repository, ready-PR scope, then validate real provider and hostile-input
paths without making the check mandatory.

### Changes Required:

#### 1. Add the trusted advisory workflow

**File**: `.github/workflows/pr-ai-review.yml`

**Intent**: Run the reviewed base-branch implementation with least privilege,
bounded spend, and one idempotent human-facing comment.

**Contract**: A `pull_request_target` workflow handles `opened` and
`ready_for_review`, then guards on a public repository, same-repository head,
and non-draft state. It runs on `ubuntu-24.04`, declares only `contents: read`
and `pull-requests: write`, and passes the workflow-scoped built-in
`GITHUB_TOKEN` only to the worker step. It uses
`actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` and
`astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9`
configured for `uv` `0.12.1`, explicitly
checks out the base SHA with `persist-credentials: false`, installs locked
dependencies from that trusted revision, and never references a PR head or
merge ref for checkout or execution.

Concurrency is keyed by PR number with cancellation of superseded runs.
Untrusted event fields remain in `GITHUB_EVENT_PATH` rather than being inserted
into shell source. The worker command is exactly `uv run python pr_review.py`;
standard `GITHUB_REPOSITORY` and `GITHUB_API_URL` identify the API target.
`OPENROUTER_API_KEY` is exposed only to the worker step;
`OPENROUTER_MODEL` is read from a repository variable. The workflow runs
no application tests, PR scripts, dependency definitions from the PR, generated
shell, model tool calls, or commands proposed by the model.

On safe provider/configuration/validation failure, the reviewer upserts its
marked unavailable notice and the job fails. Comment-publication failure also
fails the job. Input truncation or binary omission is a successful but visibly
incomplete review. The workflow is not configured as a required branch check.

#### 2. Extend workflow contract tests

**File**: `tests/test_pr_workflows.py`

**Intent**: Make the privileged workflow's trust boundary executable and
reviewer-visible.

**Contract**: Structural tests assert exact event types and eligibility guards,
`ubuntu-24.04`, least-privilege permissions, the exact checkout/setup-uv SHAs
and `uv` `0.12.1`, base-SHA checkout, `persist-credentials: false`, concurrency,
the `GITHUB_TOKEN`/event/repository/API input contract, repository
variable/secret names,
and absence of PR-head checkout, `refs/pull`, app-test execution, dynamic shell
interpolation, broad write permissions, automatic approval/merge/push, and
model tools. The quality workflow remains independent and secret-free.

#### 3. Document enablement, evidence, and rollback

**File**: `README.md`

**Intent**: Make one-time GitHub/OpenRouter setup, manual canaries, and rollback
safe and repeatable.

**Contract**: Documentation includes the complete GitHub resource inventory and
states that merging the workflow files is deployment: GitHub provisions and
destroys the runner for every event, with no separately operated service. It
requires confirming Actions PR-comment permission,
setting the explicit model variable, installing the dedicated capped key,
checking provider privacy/model compatibility, and retaining non-secret canary
evidence. Rollback disables/removes only `pr-ai-review.yml` or its secret;
deterministic CI remains active. Any future branch-protection requirement is
rolled back separately, and the marked bot comment may be manually removed
without touching human comments.

### Success Criteria:

#### Automated Verification:

- Workflow security-contract tests pass: `uv run pytest tests/test_pr_workflows.py -v`
- Reviewer tests pass: `uv run pytest tests/test_pr_review.py -v`
- Complete PostgreSQL suite and coverage floor pass:
  `uv run pytest tests/ -v --cov --cov-branch --cov-report=term-missing`
- Lint passes: `uv run ruff check .`
- Type checking passes: `uv run mypy .`
- `git check-ignore` and `git ls-files` confirm both workflows and the rubric
  are trackable while unrelated `.github/**` content remains ignored.

#### Manual Verification:

- Configure `OPENROUTER_MODEL` and the dedicated $5-capped
  `OPENROUTER_API_KEY`; record the model slug, configuration date, and provider
  privacy/structured-output confirmation without recording any secret.
- Open a public same-repository, non-draft canary PR containing inert shell text,
  prompt-injection instructions, hostile Markdown/control characters, a binary
  file, oversized text, and sentinel exfiltration bait. Record the PR/run URLs
  and confirm no PR-head checkout or execution occurs and no sentinel appears
  in logs/comments.
- Confirm the single marked comment reports the exact head SHA, requested and
  returned model, reviewed/omitted/binary/truncated counts, concise findings,
  test gaps, uncertainty, and advisory disclaimer.
- Re-run the workflow and confirm it updates the same marked bot comment without
  duplicating it or modifying any human/unmarked comment.
- Exercise invalid-key, 429, timeout, malformed-response, and unavailable-model
  canaries; record run URLs and confirm each produces only a safe unavailable
  notice, fails the advisory check, and leaves deterministic CI unaffected.
- Open or simulate a private-repository PR, fork PR, and draft PR; confirm the AI
  job is skipped while the deterministic quality workflow remains available.
- Perform a rollback drill by disabling the AI workflow or removing its secret;
  confirm provider calls/comments stop and the quality workflow still passes.

**Implementation Note**: Human confirmation of the canary evidence and rollback
drill is required before considering the AI workflow operational. Do not add it
to required branch protection in this change.

---

## Testing Strategy

### Unit Tests

- Pure configuration, context assembly, truncation, validation, and Markdown
  rendering behavior.
- Structured result bounds, invalid paths/lines/enums, extra fields, and unsafe
  control/Markdown content.
- Retry classification and exact attempt counts for every supported provider
  failure class.
- Stable marker selection and create/update behavior with unrelated human and
  bot comments present.
- Sentinel-secret absence across success and failure paths.

### Integration Tests

- Mocked GitHub REST pagination, PR metadata/head verification, file retrieval,
  and comment create/update failures.
- Mocked OpenRouter request/response contracts through respx with no live
  network effects.
- Static structural assertions over both workflow files.
- Existing full application suite against disposable PostgreSQL with enforced
  line/branch coverage.

### Manual Testing Steps

1. Prove the quality workflow goes red independently for lint, test, and
   coverage regressions, then green after restoration.
2. Validate the OpenRouter key cap, model compatibility, privacy routing, and
   repository Actions permissions without exposing credentials.
3. Run the hostile-input AI canary and inspect the exact reviewed SHA, model,
   omissions, findings, logs, and absence of execution/secret leakage.
4. Re-run to verify single-comment idempotency and exercise provider failure
   notices.
5. Verify private, fork, and draft eligibility guards and complete the rollback
   drill while deterministic CI remains green.

## Performance Considerations

- Review at most 50 files and 64 KiB of textual diff input; disclose all omitted
  and binary content.
- Bound model output to 2,000 tokens, 10 findings, 8 test gaps, and 5
  uncertainties.
- Use a 45-second OpenRouter timeout and at most two total attempts with bounded
  retry delay.
- Key concurrency by PR number to prevent duplicate provider calls and comment
  races.
- Keep deterministic static checks separable from PostgreSQL tests so reviewers
  can identify failures quickly; do not parallelize DB tests on one database.

## Migration Notes

No application or database migration is required. Rollout is additive and
reversible by workflow:

1. Phase 1 deterministic CI can remain enabled independently.
2. Removing/disabling `.github/workflows/pr-ai-review.yml` or removing its
   secret stops all OpenRouter calls and bot comments.
3. The reviewer module, tests, and rubric may remain tracked while publication
   is disabled.
4. If branch protection is changed outside this plan, remove the AI requirement
   separately; this plan never makes it required.
5. Existing marked bot comments are retained as historical output or removed
   manually; rollback never edits human comments.

## References

- Change intent: `context/changes/pr-pipeline/change.md`
- Frame brief: `context/changes/pr-pipeline/frame.md`
- Related research: `context/changes/pr-pipeline/research.md`
- Testing policy: `context/foundation/test-plan.md:13-18,91-98,122-170`
- Product invariants: `AGENTS.md:5-17`
- Existing commands and DB contract: `README.md:18-33,168-175`
- Dependency and tool configuration: `pyproject.toml:6-42`
- Local quality hooks: `lefthook.yml:1-9`
- PostgreSQL fixtures: `tests/conftest.py:15-57`
- Seed clean-checkout dependency: `tests/test_seed_import.py:13-95`
- OpenRouter provider routing:
  `https://openrouter.ai/docs/guides/routing/provider-selection`
- OpenRouter structured outputs:
  `https://openrouter.ai/docs/guides/features/structured-outputs`
- OpenRouter guardrails:
  `https://openrouter.ai/docs/guides/features/guardrails/overview`
- GitHub pull request target security:
  `https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request_target`
- GitHub secure use:
  `https://docs.github.com/en/actions/reference/security/secure-use`
- GitHub-hosted runner labels:
  `https://docs.github.com/en/actions/reference/runners/github-hosted-runners`
- GitHub pull-request REST endpoints:
  `https://docs.github.com/en/rest/pulls/pulls?apiVersion=2022-11-28`
- GitHub issue-comment REST endpoints:
  `https://docs.github.com/en/rest/issues/comments?apiVersion=2022-11-28`
- Pinned checkout release (`v7.0.1`):
  `https://github.com/actions/checkout/commit/3d3c42e5aac5ba805825da76410c181273ba90b1`
- Pinned setup-uv release (`v9.0.0`):
  `https://github.com/astral-sh/setup-uv/commit/c771a70e6277c0a99b617c7a806ffedaca235ff9`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Reproducible Deterministic Quality Gate

#### Automated

- [x] 1.1 Ignored-path contract passes — 18ff786
- [x] 1.2 Locked dependencies install — 18ff786
- [x] 1.3 Lint passes — 18ff786
- [x] 1.4 Type checking passes — 18ff786
- [x] 1.5 Full PostgreSQL suite passes with configured line/branch coverage and the recorded baseline — 18ff786
- [x] 1.6 Clean-checkout simulation confirms only intended ignored assets are tracked — 18ff786

#### Manual

- [ ] 1.7 Canary PR exposes understandable quality and coverage evidence
- [ ] 1.8 Ruff, test, and coverage regressions each fail visibly and recover to green
- [ ] 1.9 CI uses only a disposable test database and exposes no production/provider secret

### Phase 2: Bounded AI Reviewer Core

#### Automated

- [x] 2.1 Reviewer unit and HTTP-contract tests pass
- [x] 2.2 Complete suite remains green with the Phase 1 coverage floor
- [x] 2.3 Lint passes
- [x] 2.4 Type checking passes
- [x] 2.5 Sentinel-secret assertions pass across all captured surfaces

#### Manual

- [x] 2.6 Rendered fixtures are concise, evidence-backed, repository-specific, uncertain where appropriate, and advisory
- [x] 2.7 Mocked request evidence confirms model, schema, limits, no-tools, and privacy contracts
- [x] 2.8 Dedicated key has a $5 monthly cap and model allowlist without recording secrets

### Phase 3: Advisory PR Publication

#### Automated

- [ ] 3.1 Workflow security-contract tests pass
- [ ] 3.2 Reviewer tests pass
- [ ] 3.3 Complete PostgreSQL suite and coverage floor pass
- [ ] 3.4 Lint passes
- [ ] 3.5 Type checking passes
- [ ] 3.6 Intended workflows and rubric are trackable while unrelated ignored content remains ignored

#### Manual

- [ ] 3.7 Explicit model and capped key are configured with verified provider privacy and structured-output support
- [ ] 3.8 Hostile-input canary proves no PR-head execution or sentinel leakage
- [ ] 3.9 Marked comment reports exact SHA, model, omissions, findings, uncertainty, and advisory status
- [ ] 3.10 Rerun updates one marked bot comment without touching other comments
- [ ] 3.11 Provider failure canaries produce safe notices and leave deterministic CI independent
- [ ] 3.12 Private, fork, and draft PRs skip AI while retaining deterministic CI
- [ ] 3.13 AI rollback stops provider activity while deterministic CI remains active
