# Pull Request Quality and AI Review Worker Pipeline — Plan Brief

> Full plan: `context/changes/pr-pipeline/plan.md`
> Frame brief: `context/changes/pr-pipeline/frame.md`
> Research: `context/changes/pr-pipeline/research.md`

## What & Why

Pull requests lack a consistent, enforced, reviewer-visible evidence baseline,
so review completeness and toil depend on individual reviewer habits;
qualitative AI triage is a secondary aid, not proof that a change is healthy.
This plan adds deterministic PR checks first, then bounded OpenRouter triage.

## Starting Point

Pytest, Ruff, mypy, HTTP test tools, and PostgreSQL fixtures exist, but no
GitHub workflow or coverage policy is tracked. A clean checkout also lacks the
ignored seed CSV required by the import tests.

## Desired End State

Every eligible PR visibly proves lint, typing, full PostgreSQL-backed tests, and
measured coverage. Public, same-repository, ready PRs also receive one advisory
AI comment from a one-shot GitHub Actions worker, not a separately deployed bot.

## Key Decisions Made

| Decision | Choice | Why | Source |
| --- | --- | --- | --- |
| Primary evidence | Deterministic CI first | AI cannot prove tests or coverage. | Frame |
| Coverage | Measured baseline ratchet | Enforces non-regression without an arbitrary target. | Plan |
| AI scope/trigger | Public, same-repo, non-draft; opened/ready | Bounds disclosure/spend; later commits are not a current concern. | Frame / Plan |
| Provider policy | Explicit model, $5 key, ZDR/data denial | Makes processing bounded and replaceable. | Research / Plan |
| Publication | Advisory comment; safe failure notice | Humans remain authoritative and outages stay visible. | Research / Plan |
| Worker software | Python 3.12 + `httpx` + Pydantic | Uses the existing stack and direct REST contracts; no agent/provider SDK. | Frame |
| Runtime | Ephemeral `ubuntu-24.04` Actions VM | GitHub hosts and destroys each run; there is no external deployment. | Frame / Plan |
| GitHub identity | Built-in `GITHUB_TOKEN` | Workflow-scoped least privilege avoids PATs and GitHub Apps. | Plan |

## Scope

**In scope:** reproducible seed; Ruff, mypy, pytest, PostgreSQL and coverage;
separate workflows; bounded worker; idempotent comment; canary and rollback.

**Out of scope:** private/fork/draft AI review; autonomous actions; PR-code
execution with secrets; required AI gates; SDK/framework/App/container/service
infrastructure; changed-lines coverage or later-commit AI refresh.

## Architecture / Approach

The unprivileged quality workflow runs PR code against disposable PostgreSQL.
Separately, `pull_request_target` starts an ephemeral `ubuntu-24.04` runner and
executes trusted `uv run python pr_review.py`; the worker uses `GITHUB_TOKEN` for
bounded GitHub REST input/output and `httpx` plus Pydantic for OpenRouter REST.
GitHub destroys the runner after it updates one marked comment.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Quality gate | Green tests plus enforced measured coverage | Irreproducible seed or database setup. |
| 2. Reviewer core | Tested policy, provider boundary, and renderer | Injection, unbounded data, or secret exposure. |
| 3. Publication | Least-privilege workflow, canaries, rollback | Privileged workflow executes PR content. |

**Prerequisites:** GitHub workflow permission; public repository for AI;
PR-comment permission; explicit compatible OpenRouter model; dedicated $5 key.

**Estimated effort:** About three implementation sessions plus manual canaries.

## Open Risks & Assumptions

- The current 42 KiB source-backed seed corpus is intended to become tracked.
- A weak measured baseline is prevented from regressing, not repaired here.
- Public code still traverses provider infrastructure despite privacy controls.
- Model/provider compatibility and Actions permissions need a real canary.

## Success Criteria (Summary)

- Every eligible PR exposes actionable Ruff, mypy, test, and coverage evidence.
- Eligible PRs receive exactly one safe, bounded, repository-specific AI comment.
- Hostile-input/failure canaries prove no execution, leakage, duplicates, or
  coupling; rollback stops AI while deterministic CI stays active.
