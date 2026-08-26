---
starter_id: fastapi
package_manager: uv
project_name: az-limits
hints:
  language_family: python
  team_size: solo
  deployment_target: railway
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
---

## Why this stack

AzLimits is a small-scale, provenance-backed Azure-limitations API with an MCP
tool as its primary agent surface, built solo in a 3-week after-hours window.
FastAPI is the recommended default for a Python API and clears all four
agent-friendly criteria: its Pydantic schemas make every result field (source
URL, quote, confidence, status) an explicit typed contract, and auto-generated
OpenAPI docs suit the secondary human REST persona and the MCP tool boundary.
Auth is the one gap — FastAPI does not bundle it, so GitHub OAuth and hashed
API tokens (FR-001/004/006) are added via libraries; the user chose this over
Django's batteries-included but heavier, untyped, web/admin-shaped alternative
to keep the stack typed and API-shaped. Railway is the selected deployment
target. GitHub Actions runs the canonical quality workflow for every final
`main` SHA, then performs one serialized Railway CLI deployment and verifies
the runtime SHA plus `/health`; Railway native branch autodeploy remains
disabled. Bootstrapper confidence is first-class, so scaffolding should be
mostly smooth with occasional manual steps around auth, MCP wiring, and
production environment configuration.
