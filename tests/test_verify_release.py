import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

import verify_release as verify_release_module
from verify_release import (
    RetryPolicy,
    VerificationError,
    _response_has_expected_origin,
    verify_release,
)

FULL_SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER_SHA = "89abcdef0123456789abcdef0123456789abcdef"
DEPLOYMENT_ID = "7422c95b-c604-46bc-9de4-b7a43e1fd53d"
BASE_URL = "https://azlimits.example"
POLICY = RetryPolicy(
    attempts=3,
    request_timeout_seconds=0.1,
    overall_timeout_seconds=1.0,
    interval_seconds=0,
)


def _write_inputs(
    tmp_path: Path,
    *,
    up_lines: list[object] | None = None,
    deployments: object | None = None,
) -> tuple[Path, Path, Path]:
    up_path = tmp_path / "railway-up.jsonl"
    up_path.write_text(
        "\n".join(
            json.dumps(line)
            for line in (up_lines or [{"message": "building"}, {"status": "success"}])
        )
        + "\n",
        encoding="utf-8",
    )
    list_path = tmp_path / "railway-deployments.json"
    if deployments is None:
        deployments = [
            {
                "id": DEPLOYMENT_ID,
                "status": "SUCCESS",
                "createdAt": "2026-08-26T10:00:00Z",
                "meta": {"message": FULL_SHA, "build": "safe ignored metadata"},
            }
        ]
    list_path.write_text(json.dumps(deployments), encoding="utf-8")
    return up_path, list_path, tmp_path / "release-evidence.json"


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def _run(
    tmp_path: Path,
    handler: Callable[[httpx.Request], httpx.Response],
    **kwargs: Any,
) -> dict[str, Any]:
    up_path, list_path, output_path = _write_inputs(
        tmp_path,
        up_lines=kwargs.pop("up_lines", None),
        deployments=kwargs.pop("deployments", None),
    )
    with _client(handler) as client:
        return verify_release(
            expected_sha=kwargs.pop("expected_sha", FULL_SHA),
            base_url=kwargs.pop("base_url", BASE_URL),
            up_result_path=up_path,
            deployment_list_path=list_path,
            output_path=output_path,
            client=client,
            policy=kwargs.pop("policy", POLICY),
            sleeper=lambda _: None,
            **kwargs,
        )


def test_success_correlates_deployment_and_checks_version_before_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requested_paths: list[str] = []
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/version":
            return httpx.Response(200, json={"git_sha": FULL_SHA})
        return httpx.Response(200, json={"status": "ok"})

    evidence = _run(tmp_path, handler, summary_path=summary_path)

    assert requested_paths == ["/version", "/health"]
    assert evidence == json.loads(
        (tmp_path / "release-evidence.json").read_text(encoding="utf-8")
    )
    assert evidence["source_git_sha"] == FULL_SHA
    assert evidence["quality"] == {"github_run_id": "123456"}
    assert evidence["railway"] == {
        "deployment_id": DEPLOYMENT_ID,
        "status": "SUCCESS",
        "created_at": "2026-08-26T10:00:00Z",
        "up_status": "SUCCESS",
    }
    assert evidence["version"]["git_sha"] == FULL_SHA
    assert evidence["health"]["status_code"] == 200
    assert evidence["verification"]["status"] == "success"
    summary = summary_path.read_text(encoding="utf-8")
    assert FULL_SHA in summary
    assert DEPLOYMENT_ID in summary
    assert "Health HTTP status: `200`" in summary
    assert "Quality run ID: `123456`" in summary
    assert "Version verified at:" in summary
    assert "Health verified at:" in summary


@pytest.mark.parametrize("observed_sha", [OTHER_SHA, "unknown", "01234567", "A" * 40])
def test_rejects_mismatched_unknown_or_malformed_runtime_sha(
    tmp_path: Path, observed_sha: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"git_sha": observed_sha})

    with pytest.raises(VerificationError) as error:
        _run(tmp_path, handler)

    assert error.value.code in {"version_sha_mismatch", "version_invalid_sha"}
    evidence = json.loads(
        (tmp_path / "release-evidence.json").read_text(encoding="utf-8")
    )
    assert evidence["verification"]["status"] == "failed"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json={"git_sha": FULL_SHA, "branch": "main"}),
        httpx.Response(200, json=[FULL_SHA]),
    ],
)
def test_rejects_malformed_version_json(
    tmp_path: Path, response: httpx.Response
) -> None:
    with pytest.raises(VerificationError) as error:
        _run(tmp_path, lambda request: response)

    assert error.value.code == "version_malformed_json"


def test_health_failure_cannot_be_satisfied_by_matching_version(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/version":
            return httpx.Response(200, json={"git_sha": FULL_SHA})
        return httpx.Response(503)

    with pytest.raises(VerificationError) as error:
        _run(tmp_path, handler)

    assert error.value.code == "endpoint_http_failure"


def test_transient_responses_are_retried_with_a_fixed_bound(tmp_path: Path) -> None:
    counts = {"/version": 0, "/health": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counts[request.url.path] += 1
        if counts[request.url.path] == 1:
            return httpx.Response(503)
        if request.url.path == "/version":
            return httpx.Response(200, json={"git_sha": FULL_SHA})
        return httpx.Response(200)

    evidence = _run(tmp_path, handler)

    assert counts == {"/version": 2, "/health": 2}
    assert evidence["version"]["attempts"] == 2
    assert evidence["health"]["attempts"] == 2


def test_timeout_exhaustion_is_bounded_and_safe(tmp_path: Path) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("secret raw provider response", request=request)

    with pytest.raises(VerificationError) as error:
        _run(tmp_path, handler)

    assert error.value.code == "request_timeout"
    assert attempts == POLICY.attempts
    output = (tmp_path / "release-evidence.json").read_text(encoding="utf-8")
    assert "secret raw provider response" not in output


def test_redirect_is_rejected_without_following_cross_origin_location(
    tmp_path: Path,
) -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(302, headers={"location": "https://attacker.example/"})

    with pytest.raises(VerificationError) as error:
        _run(tmp_path, handler)

    assert error.value.code == "redirect_rejected"
    assert requests == 1


def test_cross_origin_response_is_rejected() -> None:
    foreign_request = httpx.Request("GET", "https://attacker.example/version")
    response = httpx.Response(200, request=foreign_request)

    assert not _response_has_expected_origin(
        response, ("https", "azlimits.example", None)
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "http://azlimits.example",
        "https://user:password@azlimits.example",
        "https://azlimits.example?token=secret",
    ],
)
def test_non_https_or_credential_bearing_base_url_is_rejected(
    tmp_path: Path, base_url: str
) -> None:
    with pytest.raises(VerificationError) as error:
        _run(tmp_path, lambda request: httpx.Response(500), base_url=base_url)

    assert error.value.code == "invalid_base_url"


@pytest.mark.parametrize(
    ("deployments", "expected_code"),
    [
        ([], "railway_deployment_ambiguous"),
        (
            [
                {
                    "id": DEPLOYMENT_ID,
                    "status": "SUCCESS",
                    "createdAt": "2026-08-26T10:00:00Z",
                    "meta": {"message": FULL_SHA},
                },
                {
                    "id": "a1b2c3d4-e5f6-4890-abcd-ef1234567890",
                    "status": "SUCCESS",
                    "createdAt": "2026-08-26T10:01:00Z",
                    "meta": {"message": FULL_SHA},
                },
            ],
            "railway_deployment_ambiguous",
        ),
        (
            [
                {
                    "id": DEPLOYMENT_ID,
                    "status": "FAILED",
                    "createdAt": "2026-08-26T10:00:00Z",
                    "meta": {"message": FULL_SHA},
                }
            ],
            "railway_deployment_failed",
        ),
    ],
)
def test_missing_ambiguous_or_failed_deployment_is_rejected(
    tmp_path: Path, deployments: object, expected_code: str
) -> None:
    with pytest.raises(VerificationError) as error:
        _run(
            tmp_path,
            lambda request: httpx.Response(500),
            deployments=deployments,
        )

    assert error.value.code == expected_code


@pytest.mark.parametrize("terminal_status", ["failed", "crashed"])
def test_failed_railway_up_status_is_rejected(
    tmp_path: Path, terminal_status: str
) -> None:
    with pytest.raises(VerificationError) as error:
        _run(
            tmp_path,
            lambda request: httpx.Response(500),
            up_lines=[{"status": terminal_status}],
        )

    assert error.value.code == "railway_up_failed"


def test_evidence_excludes_raw_metadata_responses_and_secret_like_fields(
    tmp_path: Path,
) -> None:
    secret = "super-secret-railway-token"
    deployments = [
        {
            "id": DEPLOYMENT_ID,
            "status": "SUCCESS",
            "createdAt": "2026-08-26T10:00:00Z",
            "meta": {"message": FULL_SHA, "authorization": secret},
            "rawLogs": secret,
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/version":
            return httpx.Response(200, json={"git_sha": FULL_SHA, "token": secret})
        return httpx.Response(200, text=secret)

    with pytest.raises(VerificationError):
        _run(tmp_path, handler, deployments=deployments)

    output = (tmp_path / "release-evidence.json").read_text(encoding="utf-8")
    assert secret not in output
    assert "authorization" not in output.lower()
    assert "rawlogs" not in output.lower()


def test_invalid_expected_sha_is_not_echoed_into_failure_evidence(tmp_path: Path) -> None:
    unsafe_value = "secret-bearer-value"

    with pytest.raises(VerificationError) as error:
        _run(
            tmp_path,
            lambda request: httpx.Response(500),
            expected_sha=unsafe_value,
        )

    assert error.value.code == "invalid_expected_sha"
    output = (tmp_path / "release-evidence.json").read_text(encoding="utf-8")
    assert unsafe_value not in output
    assert json.loads(output)["source_git_sha"] is None


def test_cli_reports_success_without_printing_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called: dict[str, Any] = {}

    def fake_verify_release(**kwargs: Any) -> dict[str, Any]:
        called.update(kwargs)
        return {"verification": {"status": "success"}}

    monkeypatch.setattr(verify_release_module, "verify_release", fake_verify_release)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "verify_release.py",
            "--expected-sha",
            FULL_SHA,
            "--base-url",
            BASE_URL,
            "--up-result",
            "up.jsonl",
            "--deployment-list",
            "deployments.json",
            "--output",
            "evidence.json",
        ],
    )

    assert verify_release_module.main() == 0
    assert called["expected_sha"] == FULL_SHA
    assert called["summary_path"] == tmp_path / "summary.md"
    assert capsys.readouterr().out == "Release verification succeeded.\n"


def test_cli_reports_only_safe_failure_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_verify_release(**kwargs: Any) -> dict[str, Any]:
        raise VerificationError("version_sha_mismatch", "unsafe raw response")

    monkeypatch.setattr(verify_release_module, "verify_release", fake_verify_release)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(
        "sys.argv",
        [
            "verify_release.py",
            "--expected-sha",
            FULL_SHA,
            "--base-url",
            BASE_URL,
            "--up-result",
            "up.jsonl",
            "--deployment-list",
            "deployments.json",
            "--output",
            "evidence.json",
        ],
    )

    assert verify_release_module.main() == 1
    output = capsys.readouterr().out
    assert output == "Release verification failed: version_sha_mismatch\n"
    assert "unsafe raw response" not in output
