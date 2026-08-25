import subprocess
import tomllib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
QUALITY_WORKFLOW = ROOT / ".github" / "workflows" / "pr-quality.yml"
AI_WORKFLOW = ROOT / ".github" / "workflows" / "pr-ai-review.yml"
CHECKOUT_REF = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
SETUP_UV_REF = "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9"


def _workflow(path: Path = QUALITY_WORKFLOW) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    # PyYAML follows YAML 1.1 and parses the unquoted `on` key as True.
    if True in loaded:
        loaded["on"] = loaded.pop(True)
    return loaded


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = job.get("steps")
    assert isinstance(steps, list)
    return steps


def _runs(job: dict[str, Any]) -> list[str]:
    return [step["run"] for step in _steps(job) if "run" in step]


def _uses(job: dict[str, Any]) -> list[str]:
    return [step["uses"] for step in _steps(job) if "uses" in step]


def _is_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", path],
        cwd=ROOT,
        check=False,
    )
    return result.returncode == 0


def test_quality_workflow_event_permissions_and_runner() -> None:
    workflow = _workflow()

    assert workflow["on"] == {
        "pull_request": {"types": ["opened", "ready_for_review"]}
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"lint", "typecheck", "tests"}
    assert all(job["runs-on"] == "ubuntu-24.04" for job in workflow["jobs"].values())


def test_quality_workflow_uses_immutable_actions_and_locked_python() -> None:
    workflow = _workflow()

    for job in workflow["jobs"].values():
        assert _uses(job) == [CHECKOUT_REF, SETUP_UV_REF]
        setup_uv = _steps(job)[1]
        assert setup_uv["with"] == {"version": "0.12.1"}
        assert "uv python install 3.12" in _runs(job)
        assert "uv sync --locked --group dev" in _runs(job)


def test_quality_workflow_runs_canonical_checks() -> None:
    jobs = _workflow()["jobs"]

    assert _runs(jobs["lint"])[-1] == "uv run ruff check ."
    assert _runs(jobs["typecheck"])[-1] == "uv run mypy ."
    assert _runs(jobs["tests"])[-1] == (
        "uv run pytest tests/ -v --cov --cov-branch --cov-report=term-missing"
    )


def test_quality_workflow_uses_isolated_postgresql_without_provider_secrets() -> None:
    workflow = _workflow()
    test_job = workflow["jobs"]["tests"]
    postgres = test_job["services"]["postgres"]

    assert postgres["image"] == "postgres:16"
    assert "pg_isready" in postgres["options"]
    assert set(test_job["env"]) == {"TEST_DATABASE_URL"}
    assert "azlimits_test" in test_job["env"]["TEST_DATABASE_URL"]

    workflow_text = QUALITY_WORKFLOW.read_text(encoding="utf-8")
    assert "DATABASE_URL:" not in workflow_text.replace("TEST_DATABASE_URL:", "")
    assert "OPENROUTER" not in workflow_text
    assert "secrets." not in workflow_text
    assert "pull_request_target" not in workflow_text


def test_only_required_github_and_concept_assets_are_trackable() -> None:
    trackable = [
        ".github/workflows/pr-quality.yml",
        ".github/workflows/pr-ai-review.yml",
        ".github/pr-ai-review-rubric.md",
        "concept/azure_limitations_db.csv",
    ]
    ignored = [
        ".github/local-course-material.md",
        ".github/workflows/unplanned.yml",
        "concept/local-research.md",
        "concept/other.csv",
    ]

    assert all(not _is_ignored(path) for path in trackable)
    assert all(_is_ignored(path) for path in ignored)


def test_coverage_policy_measures_application_line_and_branch_coverage() -> None:
    configuration = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    coverage = configuration["tool"]["coverage"]

    assert coverage["run"]["branch"] is True
    assert coverage["run"]["source"] == ["."]
    assert coverage["run"]["omit"] == [
        "tests/*",
        "migrations/*",
        "azure_oracle.egg-info/*",
        ".venv/*",
    ]
    assert coverage["report"]["show_missing"] is True
    assert coverage["report"]["fail_under"] == 88


def test_ai_workflow_event_eligibility_permissions_and_runner() -> None:
    workflow = _workflow(AI_WORKFLOW)
    job = workflow["jobs"]["review"]

    assert workflow["on"] == {
        "pull_request_target": {"types": ["opened", "ready_for_review"]}
    }
    assert workflow["permissions"] == {
        "contents": "read",
        "pull-requests": "write",
    }
    assert set(workflow["jobs"]) == {"review"}
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["if"] == (
        "github.event.repository.visibility == 'public' && "
        "github.event.pull_request.head.repo.full_name == github.repository && "
        "github.event.pull_request.draft == false"
    )


def test_ai_workflow_uses_trusted_base_checkout_and_pinned_tools() -> None:
    workflow = _workflow(AI_WORKFLOW)
    steps = _steps(workflow["jobs"]["review"])

    assert _uses(workflow["jobs"]["review"]) == [CHECKOUT_REF, SETUP_UV_REF]
    assert steps[0]["with"] == {
        "ref": "${{ github.event.pull_request.base.sha }}",
        "persist-credentials": False,
    }
    assert steps[1]["with"] == {"version": "0.12.1"}
    assert _runs(workflow["jobs"]["review"]) == [
        "uv python install 3.12",
        "uv sync --locked --group dev",
        "uv run python pr_review.py",
    ]


def test_ai_workflow_serializes_runs_by_pull_request() -> None:
    workflow = _workflow(AI_WORKFLOW)

    assert workflow["concurrency"] == {
        "group": "pr-ai-review-${{ github.event.pull_request.number }}",
        "cancel-in-progress": True,
    }


def test_ai_workflow_exposes_secrets_only_to_the_worker_step() -> None:
    workflow = _workflow(AI_WORKFLOW)
    steps = _steps(workflow["jobs"]["review"])
    worker = steps[-1]

    assert worker["run"] == "uv run python pr_review.py"
    assert worker["env"] == {
        "GITHUB_TOKEN": "${{ secrets.GITHUB_TOKEN }}",
        "OPENROUTER_MODEL": "${{ vars.OPENROUTER_MODEL }}",
        "OPENROUTER_API_KEY": "${{ secrets.OPENROUTER_API_KEY }}",
    }
    assert all("env" not in step for step in steps[:-1])


def test_ai_workflow_never_executes_pull_request_content() -> None:
    workflow = _workflow(AI_WORKFLOW)
    job = workflow["jobs"]["review"]
    workflow_text = AI_WORKFLOW.read_text(encoding="utf-8")
    run_text = "\n".join(_runs(job))

    assert "pull_request.head.sha" not in workflow_text
    assert "refs/pull" not in workflow_text
    assert "github.event.pull_request.head.ref" not in workflow_text
    assert "github.head_ref" not in workflow_text
    assert "pytest" not in run_text
    assert "ruff" not in run_text
    assert "mypy" not in run_text
    assert "git push" not in run_text
    assert "gh pr" not in run_text
    assert "${{" not in run_text
    assert "tools" not in workflow_text


def test_quality_and_ai_workflows_keep_separate_trust_profiles() -> None:
    quality_text = QUALITY_WORKFLOW.read_text(encoding="utf-8")
    ai_workflow = _workflow(AI_WORKFLOW)

    assert "pull_request_target" not in quality_text
    assert "OPENROUTER" not in quality_text
    assert "secrets." not in quality_text
    assert ai_workflow["permissions"] == {
        "contents": "read",
        "pull-requests": "write",
    }
