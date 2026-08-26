# Frame Brief: Verifiable Railway releases from main

> Framing step before /10x-plan. This document captures what is *actually*
> at issue, separated from what was initially assumed.

## Reported Observation

Changes reaching `main` are not automatically and verifiably released to
Railway.

## Initial Framing (preserved)

- **User's stated cause or approach**: PR merges and direct pushes are treated
  as deployment events that a repository-owned pipeline should handle.
- **User's proposed direction**: Add a new pipeline that automatically deploys
  to Railway after a PR merge or push to `main`.
- **Pre-dispatch narrowing**: The leading concern is that production may update,
  but there is no trustworthy proof that the exact commit passed quality checks
  and became healthy.

## Dimension Map

The observation could originate at any of these dimensions:

1. **Commit identity** — the SHA that passed checks may differ from the SHA that
   reached `main` or the SHA running in production.
2. **Quality evidence** — checks may be absent or stale for the final `main`
   commit.
3. **Deployment provenance** — a release may occur without an auditable link
   from Git commit to Railway deployment. This is where the initial pipeline
   framing lands.
4. **Runtime acceptance** — a deployment may exist without observable proof of
   the running revision and process liveness.

## Hypothesis Investigation

| Hypothesis | Evidence | Verdict |
| --- | --- | --- |
| The final `main` SHA lacks fresh canonical quality evidence | `pr-quality.yml:3-5` runs only for PR `opened` and `ready_for_review`; its Ruff, mypy, and PostgreSQL/coverage jobs at `:10-61` are not connected to `main` pushes or releases. `tests/test_pr_workflows.py:47-54` preserves that limited trigger. | STRONG |
| A missing deployment pipeline is the whole problem | No deploy workflow or GitHub Deployment record exists, so the initial framing identifies a real gap. However, a trigger alone would not identify the running revision or connect it to quality and health evidence. | WEAK |
| Railway already provides sufficient Git provenance | Live Railway records expose deployment IDs, timestamps, statuses, and image digests, but no repository, branch, or Git SHA. The service source was `null` during investigation. Historical deploy evidence is manual attestation without SHA linkage (`context/archive/2026-07-20-deploy-skeleton-health/plan.md:142-146`). | NONE |
| The running application already exposes its source revision | Repository and history searches found no `/version` route, `GITHUB_SHA`, `RAILWAY_GIT_COMMIT_SHA`, `COMMIT_SHA`, `SOURCE_VERSION`, or equivalent. Current routes begin with static `/health` at `main.py:188-190`, followed by auth and limitation routes. | NONE |
| Process liveness is observable through `/health` | `main.py:188-190` defines static `{"status": "ok"}` and `tests/test_health.py:6-12` asserts HTTP 200. Railway points its activation check there (`railway.json:3-5`). The contract exists, although the live public URL returned Railway fallback 404 during investigation. | PARTIAL |
| Database-backed readiness must be part of this release acceptance | The PRD and test plan separately require dependency readiness (`context/foundation/prd.md:135`; `context/foundation/test-plan.md:83,91-97`), but the user explicitly defined this change's health evidence as process liveness only. | WEAK |

## Narrowing Signals

- The user requires the running application to reveal the deployed Git commit
  SHA somewhere observable, for example through `GET /version` or an equivalent
  API surface.
- The user defines “healthy” for this release evidence as process liveness:
  `GET /health` returns HTTP 200.
- Database-backed readiness remains a valid product/test-plan obligation, but
  it is not the acceptance boundary for this change.
- Independent investigation found no hidden runtime version endpoint, commit
  injection, or Git-linked Railway deployment metadata that would make the
  requested evidence chain already exist.

## Cross-System Convention

A verifiable release normally preserves one identity across four observable
boundaries: the source revision, the quality result for that revision, the
deployment record, and the running process. A platform deployment ID or image
digest proves that an artifact exists, but not which Git revision it represents
unless the systems carry and compare a common revision identifier.

The repository currently has pieces of this convention—deterministic checks,
Railway deployment records, and a liveness endpoint—but no shared release
identity joins them. The independent pressure test reached the same conclusion
without assuming that a new pipeline was the cause or answer.

## Reframed Problem Statement

> **The actual problem to plan around is**: Production has no observable,
> machine-verifiable release chain tying a specific `main` Git SHA to that
> SHA's quality result, its Railway deployment, the running application's
> reported SHA, and a contemporaneous `/health` 200 result.

The initial framing was directionally correct: release automation is absent and
a repository-owned pipeline may be part of the eventual plan. It was incomplete
because triggering a deployment alone would not prove which revision is running
or whether the exact revision passed checks. Addressing the reframed problem
creates evidence a human can audit without correlating timestamps or trusting a
manual deployment attestation.

## Confidence

- **HIGH** — all investigated systems independently show a missing link: no
  exact-`main` quality run, no deploy workflow, no Git SHA in Railway records,
  no runtime version identity, and no current live `/health` success. The user's
  acceptance observations also match the cross-system evidence convention.

## What Changes for /10x-plan

The plan should cover the end-to-end release evidence contract, not merely a
deployment trigger: exact-SHA quality evidence, deployment correlation, runtime
SHA identity, and process-liveness verification must all refer to one release.
Dependency-aware readiness should remain outside this change unless the user
later expands the acceptance boundary.

## References

- Source files: `.github/workflows/pr-quality.yml:3-61`,
  `tests/test_pr_workflows.py:47-54`, `main.py:188-190`,
  `tests/test_health.py:6-12`, `railway.json:3-5`
- Policy/history: `context/deployment/deploy-plan.md:21-39,128-147`,
  `context/foundation/prd.md:135`, `context/foundation/test-plan.md:83,91-97`,
  `context/archive/2026-07-20-deploy-skeleton-health/plan.md:142-146`
- Related research: `context/changes/deploy-pipeline/research.md`
- Investigation tasks: `frame_exact_sha`, `frame_deploy_provenance`,
  `frame_runtime_acceptance`, `frame_pressure_test`
