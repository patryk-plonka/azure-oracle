# Frame Brief: Faster, lower-toil pull request review

> Framing step before /10x-plan. This document captures what is *actually*
> at issue, separated from what was initially assumed.

## Reported Observation

Opening a PR currently produces no automated quality/security review summary
for a human reviewer.

## Initial Framing (preserved)

- **User's stated cause or approach**: Run an AI agent through OpenRouter to
  review PR code against code-quality and security practices.
- **User's proposed direction**: Trigger a GitHub Actions pipeline when a PR is
  created and prepare a summary for a human reviewer.
- **Pre-dispatch narrowing**: The leading concern is to “speed up the process
  and minimize the toil of reviews.” The current process depends on the
  reviewer; only `uv run ruff check .` was identified as hooked, which is not
  enough to show that tests are green or that coverage is good. Start light and
  add more later. PRs normally receive no additional commits after opening.

## Dimension Map

The observation could originate at any of these dimensions:

1. **Deterministic evidence baseline** — reviewers lack an enforced,
   reviewer-visible result for lint, typing, tests, and an agreed meaning of
   adequate coverage.
2. **Context assembly** — reviewers must reconstruct change intent, product
   invariants, risk areas, and cross-file implications from distributed
   artifacts.
3. **Risk prioritization** — reviewers lack a concise first pass identifying
   semantic, security, and missing-test risks that deterministic checks cannot
   establish. ← initial AI-summary framing
4. **Workflow freshness and noise** — automated feedback could become stale,
   duplicated, or too noisy to reduce human effort.

## Hypothesis Investigation

| Hypothesis | Evidence | Verdict |
| --- | --- | --- |
| Missing deterministic evidence is the main source of inconsistency | No tracked GitHub workflow exists; pytest, Ruff, and mypy are configured locally, but quality-gate wiring remains “not started” (`pyproject.toml:28-42`; `context/foundation/test-plan.md:91-98,122-135`). There is no coverage tool, policy, or threshold. The user explicitly identified green tests and meaningful coverage as missing evidence. | STRONG |
| Context assembly is the main source of toil | Review context is distributed across `AGENTS.md:5-17`, `context/foundation/prd.md:67-72`, and `context/foundation/test-plan.md:35-49,122-135`. Archived reviews demonstrate substantial grounding work, but the repository has no timing evidence showing this is the dominant cost. | WEAK |
| Absence of an AI risk summary is the main problem | Archived reviews found semantic and security defects after ordinary checks passed, including insecure token transport and unbounded responses (`context/archive/2026-08-16-mcp-tool-wrapper/reviews/impl-review.md:23-54`). AI-assisted triage is credible, but it cannot prove tests are green or quantify coverage, and no acceptance/false-positive data exists. | WEAK |
| Opened-only feedback creates freshness toil | Research establishes that opened-only comments can become stale (`research.md:153-155`), but the user reports that PRs normally receive no later commits. That failure mode is not present in the current workflow. | NONE |

## Narrowing Signals

- Review completeness currently depends on which reviewer handles the PR.
- The observed missing evidence is concrete: test pass/fail and whether tests
  meaningfully cover the change.
- Existing local automation does not provide an authoritative, shared PR result.
- “Good coverage” has no current measurable definition: no coverage dependency,
  configuration, baseline, or threshold exists.
- PRs normally do not change after opening, so initial-feedback freshness is not
  the present bottleneck.
- The desired rollout is deliberately incremental rather than an attempt to
  automate every review concern immediately.

## Cross-System Convention

The repository's own test strategy says to use the cheapest deterministic check
that produces real signal and not place an AI judge over behavior that a normal
assertion can verify (`context/foundation/test-plan.md:13-18,104-114`). It also
already calls for PR-level lint/typecheck, unit/integration, provenance,
auth/license, and readiness gates (`context/foundation/test-plan.md:122-135`).

Historical implementation reviews confirm the complementary boundary. Green
pytest, Ruff, and mypy results did not catch every cross-file, boundary, or
security defect (`context/archive/2026-08-16-mcp-tool-wrapper/reviews/impl-review.md:23-83`).
Deterministic evidence should establish facts; qualitative review should focus
human or AI attention on risks that those facts cannot settle.

## Reframed Problem Statement

> **The actual problem to plan around is**: Pull requests lack a consistent,
> enforced, reviewer-visible evidence baseline, so review completeness and toil
> depend on individual reviewer habits; qualitative AI triage is a secondary
> aid, not the proof that a change is healthy.

This reframe preserves the value of the proposed OpenRouter review while making
the intended outcome precise. Faster review requires reviewers to receive
trusted evidence about green checks and an explicit coverage policy first, then
high-signal guidance about semantic, security, and missing-test risks that
deterministic checks cannot assess.

## Confidence

- **HIGH** — the user identified the missing evidence directly; live
  configuration proves the tools and tests exist but are not enforced in PR CI;
  the repository's test strategy independently specifies the same missing gate;
  and a hypothesis-blind pressure test reached the same conclusion.

## What Changes for /10x-plan

The plan should target a lightweight, reproducible PR evidence baseline and a
clear initial coverage policy as the primary toil reduction. The OpenRouter
summary should be scoped as an advisory layer for repository-specific,
cross-file, security, and test-gap reasoning, with success measured by reviewer
time and signal quality rather than by the existence of a bot comment.

## References

- Source files: `.gitignore:26-29`, `pyproject.toml:28-42`, `lefthook.yml:1-9`,
  `context/foundation/test-plan.md:13-18,91-98,104-135`
- Historical evidence:
  `context/archive/2026-08-16-mcp-tool-wrapper/reviews/impl-review.md:23-83`,
  `context/archive/2026-08-16-cli-onboarding-bootstrap/reviews/impl-review.md:56-105`
- Related research: `context/changes/pr-pipeline/research.md`
- Investigation tasks: `/root/frame_gates`, `/root/frame_context`,
  `/root/frame_workflow`, `/root/frame_pressure`

---

## Follow-up Frame: Review-worker architecture clarity

### Reported Observation

The plan does not make it clear what software constitutes the review bot, which
GitHub resources it needs, or where and how it runs.

### Initial Framing (preserved)

- **User's stated cause or approach**: The SDK, GitHub-resource, and deployment
  decisions may still be unresolved.
- **User's proposed direction**: Establish an understandable end-to-end picture
  before implementation.
- **Pre-dispatch narrowing**: SDK, GitHub resources, and deployment are
  inseparable; the leading concern is the end-to-end system.

### Dimension Map

1. **Bot implementation** — whether “AI agent” names an agent framework or a
   small program calling APIs.
2. **GitHub control plane** — whether events, permissions, credentials, config,
   and comment resources have been chosen.
3. **Execution environment** — whether an external service/container is needed
   or the worker runs ephemerally in Actions.
4. **Plan communication** — whether choices exist but are scattered and phrased
   as constraints rather than one runtime inventory. ← initial framing

### Hypothesis Investigation

| Hypothesis | Evidence | Verdict |
| --- | --- | --- |
| The SDK/framework choice is unresolved | Research selects Python 3.12, existing `httpx` and Pydantic, a direct OpenRouter chat-completions request, and no tools; the plan names `pr_review.py` (`research.md:43-45,71-77,167-192`; `plan.md:286-322`; `pyproject.toml:6-15`). | NONE |
| GitHub resources are unresolved | The plan specifies two workflows, events, guards, permissions, base checkout, concurrency, a repository secret/variable, REST data retrieval, and one marked comment (`plan.md:91-98,190-217,295-322,393-447`). | NONE |
| A separate deployment is unresolved | Workflow disablement or secret removal stops the reviewer, and no server, image, queue, database, webhook receiver, or GitHub App is planned (`plan.md:541-550`). | NONE |
| The end-to-end architecture is poorly communicated | The brief summarizes trust flow but never plainly says there is no SDK/framework or external deployment; runner, GitHub authentication, CLI inputs, and exact REST bindings are only implied (`plan-brief.md:52-69`). | STRONG |

### Narrowing Signals

- The user needs the SDK, GitHub resources, and lifecycle explained as one
  system, not as isolated details.
- Independent investigations found no competing architecture in the artifacts.
- Calling the component an “AI agent” suggests autonomy and an agent SDK even
  though the plan explicitly forbids tools/functions (`plan.md:301-304,411-413`).
- Runner ownership, the `GITHUB_TOKEN`, worker entrypoint inputs, and exact REST
  endpoints remain insufficiently explicit for implementation handoff.

### Cross-System Convention

An event-triggered GitHub Actions worker should be described as a complete
lifecycle: event, ephemeral runner, executable, credentials/configuration,
external APIs, output resource, and termination. The current plan contains
these pieces but does not present that inventory in one place.

### Reframed Problem Statement

> **The actual problem to plan around is**: The architecture is mostly decided,
> but the plan's scattered contracts and “AI agent” terminology obscure that it
> is a one-shot Python PR review worker running in GitHub Actions, while several
> concrete runtime bindings remain implicit.

The intended system is a custom Python module using `httpx` and Pydantic to call
GitHub REST and OpenRouter REST directly. GitHub Actions supplies the ephemeral
runtime; no persistent bot service is deployed. The remaining gap is an
explicit, implementation-ready runtime/resource inventory, not a new SDK or
hosting decision.

### Confidence

- **HIGH** — three dimension investigations and a hypothesis-blind pressure
  test independently found the same architecture and communication gap, with no
  contradictory deployment design.

### What Changes for /10x-plan

The plan should explicitly name the component an AI PR review worker, show its
end-to-end lifecycle, list every GitHub resource, and lock the runner,
`GITHUB_TOKEN`, entrypoint input, and REST endpoint contracts. It should state
plainly that no OpenRouter/GitHub SDK, agent framework, GitHub App, container, or
always-on service is deployed.

### References

- Source files: `pyproject.toml:6-15`, `context/changes/pr-pipeline/plan.md:91-109,190-217,286-322,393-447,541-550`, `context/changes/pr-pipeline/plan-brief.md:52-69`
- Related research: `context/changes/pr-pipeline/research.md:43-45,71-77,123-192,242-261`
- Investigation tasks: `/root/frame_sdk`, `/root/frame_github_resources`,
  `/root/frame_deployment`, `/root/frame_arch_pressure`
