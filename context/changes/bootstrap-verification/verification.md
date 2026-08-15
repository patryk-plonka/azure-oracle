---
bootstrapped_at: 2026-07-19T00:00:00Z
starter_id: fastapi
starter_name: FastAPI
project_name: az-limits
language_family: python
package_manager: uv
cwd_strategy: native-cwd
bootstrapper_confidence: first-class
phase_3_status: ok
audit_command: pip-audit
---

## Hand-off

Verbatim copy of `context/foundation/tech-stack.md`.

Frontmatter:

```yaml
starter_id: fastapi
package_manager: uv
project_name: az-limits
hints:
  language_family: python
  team_size: solo
  deployment_target: fly
  ci_provider: github-actions
  ci_default_flow: auto-deploy-on-merge
  bootstrapper_confidence: first-class
  path_taken: standard
  quality_override: false
  self_check_answers: null
  has_auth: true
  has_payments: false
  has_realtime: false
  has_ai: false
  has_background_jobs: false
```

Why this stack:

> AzLimits is a small-scale, provenance-backed Azure-limitations API with an MCP
> tool as its primary agent surface, built solo in a 3-week after-hours window.
> FastAPI is the recommended default for a Python API and clears all four
> agent-friendly criteria: its Pydantic schemas make every result field (source
> URL, quote, confidence, status) an explicit typed contract, and auto-generated
> OpenAPI docs suit the secondary human REST persona and the MCP tool boundary.
> Auth is the one gap — FastAPI does not bundle it, so GitHub OAuth and hashed
> API tokens (FR-001/004/006) are added via libraries; the user chose this over
> Django's batteries-included but heavier, untyped, web/admin-shaped alternative
> to keep the stack typed and API-shaped. Deployment targets Fly (the starter
> default) with GitHub Actions auto-deploying on merge. Bootstrapper confidence is
> first-class, so scaffolding should be mostly smooth with occasional manual steps
> around the auth and MCP wiring.

## Pre-scaffold verification

| Signal      | Value                                          | Severity | Notes                                             |
| ----------- | ---------------------------------------------- | -------- | ------------------------------------------------- |
| npm package | not run                                        | n/a      | non-JS starter (language_family: python)          |
| GitHub repo | not run                                        | n/a      | card docs_url (https://fastapi.tiangolo.com) is not a github.com URL |

No recency signal available for this starter. Proceeded with no warning.

## Scaffold log

**Resolved invocation**: `uv init . && uv add fastapi uvicorn`
**Strategy**: native-cwd
**Exit code**: 0
**Pre-flight files-to-touch**: pyproject.toml, .python-version, main.py, README.md (README.md skipped — already present, preserved)
**Files written by CLI**: pyproject.toml, .python-version, main.py, uv.lock, .venv/
**Pre-existing files preserved**: README.md, LICENSE, concept.md, concept/, context/, .git/, .github/

Notes:
- `uv init` did not create a `.gitignore` (a `.git/` repository already existed in the directory).
- `context/` was preserved verbatim — no scaffold files targeted it.
- No conflicts detected; no `.scaffold` siblings were created.
- Dependencies installed into `.venv/`: fastapi 0.139.2, uvicorn 0.51.0, plus 12 transitive packages.

## Post-scaffold audit

**Tool**: pip-audit
**Summary**: 0 CRITICAL, 0 HIGH, 0 MODERATE, 0 LOW
**Direct vs transitive**: 0/0/0/0 direct of total 0/0/0/0 — no findings to distinguish

No known vulnerabilities found across the project's dependency tree, including the direct
dependencies (fastapi 0.139.2, uvicorn 0.51.0) and all transitive packages (annotated-types,
anyio, click, colorama, h11, idna, pydantic 2.13.4, pydantic-core, starlette 1.3.1,
typing-extensions, typing-inspection).

#### CRITICAL findings

None.

#### HIGH findings

None.

#### MODERATE findings

None.

#### LOW / INFO findings

None.

## Hints recorded but not acted on

| Hint                    | Value                |
| ----------------------- | -------------------- |
| bootstrapper_confidence | first-class          |
| quality_override        | false                |
| path_taken              | standard             |
| self_check_answers      | null                 |
| team_size               | solo                 |
| deployment_target       | fly                  |
| ci_provider             | github-actions       |
| ci_default_flow         | auto-deploy-on-merge |
| has_auth                | true                 |
| has_payments            | false                |
| has_realtime            | false                |
| has_ai                  | false                |
| has_background_jobs     | false                |

## Next steps

Next: a future skill will set up agent context (CLAUDE.md, AGENTS.md). For now, your project is scaffolded and verified — happy hacking.

Useful manual steps in the meantime:
- `git init` (if you have not already) to start your own repo history.
- Review any `.scaffold` siblings the conflict policy created and decide which version of each file to keep. (None were created this run.)
- Address audit findings per your project's risk tolerance — the full breakdown is in this log. (Clean tree this run.)
- Wire up the auth path (GitHub OAuth + hashed API tokens per FR-001/004/006) and MCP tool surface — the hand-off flagged these as the manual-touch areas for this stack.
