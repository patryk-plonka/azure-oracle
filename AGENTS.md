# Repository Guidelines

Azure Oracle (AzLimits) is a Python 3.12 FastAPI scaffold for a source-backed Azure limitations API and MCP surface. Treat the current application as intentionally minimal; the product contract is defined in @context/foundation/prd.md and the selected stack in @context/foundation/tech-stack.md.

## Hard Rules

- Return no public limitation record without its source URL, quote or excerpt, confidence, and verification state. A record without provenance is a defect.
- Never log, return, commit, or hard-code raw API tokens, OAuth credentials, or other secrets. Tokens must be stored only as hashes.
- Check token validity and the Demo license state before a protected response reaches limitation data.
- Keep the MVP API and MCP-first. Do not add a web dashboard, automatic IaC remediation, other cloud providers, or advanced billing without an explicit scope change in @context/foundation/prd.md.

## Project Structure

- `main.py` is the current executable entry point; keep application code in the repository root until a package layout is introduced deliberately.
- `concept.md` and `concept/` contain product research and the seed Azure-limitation material. Preserve source and verification metadata when evolving that dataset.
- `context/foundation/` is the project handoff: consult `prd.md` for requirements and guardrails, and `tech-stack.md` for the chosen tooling and deployment direction.
- `context/archive/` is immutable. Do not edit archived material; create a new change instead.

## Development Commands

- Run `uv sync` to create or update the local environment from `pyproject.toml` and `uv.lock`.
- Run `uv run python main.py` to execute the current scaffold entry point.
- Use `uv` for dependency changes; update both `pyproject.toml` and `uv.lock` through its normal workflow.

## Code and Tests

Use Python 3.12 or later, as declared in `pyproject.toml`. The repository currently has no configured linter, formatter, test suite, or GitHub Actions workflow; add focused tests alongside any new behavior and document the command when introducing the test runner.

## Commits

The history contains only the initial commit, so no commit-prefix convention is established. Keep commit subjects concise and imperative. Before opening a pull request, run the executable and any focused tests introduced by the change.