import subprocess
import tomllib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
QUALITY_WORKFLOW = ROOT / ".github" / "workflows" / "pr-quality.yml"
CHECKOUT_REF = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
SETUP_UV_REF = "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9"


def _workflow() -> dict[str, Any]:
    loaded = yaml.safe_load(QUALITY_WORKFLOW.read_text(encoding="utf-8"))
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
