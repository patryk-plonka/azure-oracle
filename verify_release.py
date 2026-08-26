import argparse
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx

_FULL_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_TERMINAL_RAILWAY_STATUSES = {"success", "failed", "crashed"}


class VerificationError(RuntimeError):
    """A release verification failure with a safe, stable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 6
    request_timeout_seconds: float = 5.0
    overall_timeout_seconds: float = 90.0
    interval_seconds: float = 5.0


_DEFAULT_RETRY_POLICY = RetryPolicy()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _require_full_sha(value: str) -> str:
    if _FULL_GIT_SHA.fullmatch(value) is None:
        raise VerificationError(
            "invalid_expected_sha", "Expected Git SHA must be full and lowercase."
        )
    return value


def _endpoint_urls(base_url: str) -> tuple[str, str, tuple[str, str, int | None]]:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise VerificationError(
            "invalid_base_url", "Application base URL must be a credential-free HTTPS URL."
        )

    base = base_url.rstrip("/")
    origin = (parsed.scheme, parsed.hostname.lower(), parsed.port)
    return f"{base}/version", f"{base}/health", origin


def _load_up_status(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise VerificationError(
            "railway_up_unreadable", "Railway deployment result is unavailable."
        ) from exc

    terminal_statuses: list[str] = []
    try:
        for line in lines:
            if not line.strip():
                continue
            item: object = json.loads(line)
            if isinstance(item, dict):
                status = item.get("status")
                if isinstance(status, str) and status.lower() in _TERMINAL_RAILWAY_STATUSES:
                    terminal_statuses.append(status.lower())
    except json.JSONDecodeError as exc:
        raise VerificationError(
            "railway_up_malformed", "Railway deployment result is not valid JSON lines."
        ) from exc

    if len(terminal_statuses) != 1:
        raise VerificationError(
            "railway_up_ambiguous", "Railway deployment result has no unique terminal status."
        )
    if terminal_statuses[0] != "success":
        raise VerificationError(
            "railway_up_failed", "Railway reported an unsuccessful deployment."
        )
    return "SUCCESS"


def _deployment_for_sha(path: Path, expected_sha: str) -> dict[str, str]:
    try:
        loaded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError(
            "railway_list_malformed", "Railway deployment list is unavailable or invalid."
        ) from exc

    if not isinstance(loaded, list):
        raise VerificationError(
            "railway_list_malformed", "Railway deployment list must be a JSON array."
        )

    matching: list[dict[str, Any]] = []
    for item in loaded:
        if not isinstance(item, dict):
            continue
        meta = item.get("meta")
        if isinstance(meta, dict) and meta.get("message") == expected_sha:
            matching.append(item)

    if len(matching) != 1:
        raise VerificationError(
            "railway_deployment_ambiguous",
            "Expected one Railway deployment correlated to the source SHA.",
        )

    deployment = matching[0]
    deployment_id = deployment.get("id")
    status = deployment.get("status")
    created_at = deployment.get("createdAt")
    if not isinstance(deployment_id, str):
        raise VerificationError(
            "railway_deployment_invalid", "Railway deployment ID is invalid."
        )
    try:
        UUID(deployment_id)
    except ValueError as exc:
        raise VerificationError(
            "railway_deployment_invalid", "Railway deployment ID is invalid."
        ) from exc
    if status != "SUCCESS":
        raise VerificationError(
            "railway_deployment_failed", "Correlated Railway deployment is not successful."
        )
    if not isinstance(created_at, str):
        raise VerificationError(
            "railway_deployment_invalid", "Railway deployment timestamp is invalid."
        )
    try:
        datetime.fromisoformat(created_at)
    except ValueError as exc:
        raise VerificationError(
            "railway_deployment_invalid", "Railway deployment timestamp is invalid."
        ) from exc

    return {
        "deployment_id": deployment_id,
        "status": status,
        "created_at": created_at,
    }


def _response_has_expected_origin(
    response: httpx.Response, origin: tuple[str, str, int | None]
) -> bool:
    url = response.url
    return (url.scheme, url.host.lower(), url.port) == origin


def _check_endpoint(
    *,
    client: httpx.Client,
    url: str,
    origin: tuple[str, str, int | None],
    expected_sha: str | None,
    policy: RetryPolicy,
    deadline: float,
    monotonic: Callable[[], float],
    sleeper: Callable[[float], None],
) -> dict[str, Any]:
    last_code = "endpoint_unavailable"
    for attempt in range(1, policy.attempts + 1):
        remaining = deadline - monotonic()
        if remaining <= 0:
            last_code = "verification_timeout"
            break
        try:
            response = client.get(
                url, timeout=min(policy.request_timeout_seconds, remaining)
            )
        except httpx.RequestError:
            last_code = "request_timeout"
        else:
            if not _response_has_expected_origin(response, origin):
                raise VerificationError(
                    "cross_origin_response", "Endpoint response changed HTTPS origin."
                )
            if response.is_redirect:
                raise VerificationError(
                    "redirect_rejected", "Endpoint redirects are not accepted."
                )
            if response.status_code == 200:
                if expected_sha is None:
                    return {
                        "status_code": 200,
                        "attempts": attempt,
                        "verified_at": _utc_now(),
                    }
                try:
                    payload: object = response.json()
                except json.JSONDecodeError:
                    last_code = "version_malformed_json"
                else:
                    if not isinstance(payload, dict) or set(payload) != {"git_sha"}:
                        last_code = "version_malformed_json"
                    else:
                        observed_sha = payload["git_sha"]
                        if (
                            not isinstance(observed_sha, str)
                            or _FULL_GIT_SHA.fullmatch(observed_sha) is None
                        ):
                            last_code = "version_invalid_sha"
                        elif observed_sha != expected_sha:
                            last_code = "version_sha_mismatch"
                        else:
                            return {
                                "status_code": 200,
                                "git_sha": observed_sha,
                                "attempts": attempt,
                                "verified_at": _utc_now(),
                            }
            else:
                last_code = "endpoint_http_failure"

        if attempt < policy.attempts:
            remaining = deadline - monotonic()
            if remaining > 0:
                sleeper(min(policy.interval_seconds, remaining))

    raise VerificationError(last_code, "Endpoint verification did not succeed in time.")


def _write_json(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_summary(evidence: dict[str, Any], summary_path: Path | None) -> None:
    if summary_path is None:
        return
    verification = evidence["verification"]
    lines = [
        "## Production release verification",
        "",
        f"- Status: `{verification['status']}`",
        f"- Source SHA: `{evidence['source_git_sha']}`",
        f"- Started at: `{verification['started_at']}`",
        f"- Completed at: `{verification['completed_at']}`",
    ]
    quality = evidence.get("quality")
    if isinstance(quality, dict) and quality.get("github_run_id") is not None:
        lines.append(f"- Quality run ID: `{quality['github_run_id']}`")
    railway = evidence.get("railway")
    if isinstance(railway, dict):
        lines.extend(
            [
                f"- Railway deployment: `{railway['deployment_id']}`",
                f"- Railway status: `{railway['status']}`",
                f"- Railway created at: `{railway['created_at']}`",
            ]
        )
    version = evidence.get("version")
    if isinstance(version, dict):
        lines.extend(
            [
                f"- Runtime SHA: `{version['git_sha']}`",
                f"- Version verified at: `{version['verified_at']}`",
            ]
        )
    health = evidence.get("health")
    if isinstance(health, dict):
        lines.extend(
            [
                f"- Health HTTP status: `{health['status_code']}`",
                f"- Health verified at: `{health['verified_at']}`",
            ]
        )
    if verification["status"] == "failed":
        lines.append(f"- Failure code: `{verification['failure_code']}`")
    lines.append("")
    with summary_path.open("a", encoding="utf-8") as summary:
        summary.write("\n".join(lines))


def verify_release(
    *,
    expected_sha: str,
    base_url: str,
    up_result_path: Path,
    deployment_list_path: Path,
    output_path: Path,
    summary_path: Path | None = None,
    client: httpx.Client | None = None,
    policy: RetryPolicy = _DEFAULT_RETRY_POLICY,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    started_at = _utc_now()
    safe_expected_sha = (
        expected_sha if _FULL_GIT_SHA.fullmatch(expected_sha) is not None else None
    )
    github_run_id = os.environ.get("GITHUB_RUN_ID")
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "source_git_sha": safe_expected_sha,
        "quality": {
            "github_run_id": github_run_id
            if github_run_id is not None and github_run_id.isdecimal()
            else None
        },
        "verification": {"status": "running", "started_at": started_at},
    }
    owned_client = client is None
    http_client = client or httpx.Client(follow_redirects=False)

    try:
        expected_sha = _require_full_sha(expected_sha)
        version_url, health_url, origin = _endpoint_urls(base_url)
        up_status = _load_up_status(up_result_path)
        railway = _deployment_for_sha(deployment_list_path, expected_sha)
        railway["up_status"] = up_status
        evidence["railway"] = railway

        deadline = monotonic() + policy.overall_timeout_seconds
        evidence["version"] = _check_endpoint(
            client=http_client,
            url=version_url,
            origin=origin,
            expected_sha=expected_sha,
            policy=policy,
            deadline=deadline,
            monotonic=monotonic,
            sleeper=sleeper,
        )
        evidence["health"] = _check_endpoint(
            client=http_client,
            url=health_url,
            origin=origin,
            expected_sha=None,
            policy=policy,
            deadline=deadline,
            monotonic=monotonic,
            sleeper=sleeper,
        )
        evidence["verification"] = {
            "status": "success",
            "started_at": started_at,
            "completed_at": _utc_now(),
        }
    except VerificationError as exc:
        evidence["verification"] = {
            "status": "failed",
            "failure_code": exc.code,
            "started_at": started_at,
            "completed_at": _utc_now(),
        }
        _write_json(output_path, evidence)
        _append_summary(evidence, summary_path)
        raise
    finally:
        if owned_client:
            http_client.close()

    _write_json(output_path, evidence)
    _append_summary(evidence, summary_path)
    return evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify one Railway production release.")
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--up-result", required=True, type=Path)
    parser.add_argument("--deployment-list", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    summary_value = os.environ.get("GITHUB_STEP_SUMMARY")
    summary_path = Path(summary_value) if summary_value else None
    try:
        verify_release(
            expected_sha=args.expected_sha,
            base_url=args.base_url,
            up_result_path=args.up_result,
            deployment_list_path=args.deployment_list,
            output_path=args.output,
            summary_path=summary_path,
        )
    except VerificationError as exc:
        print(f"Release verification failed: {exc.code}")
        return 1
    print("Release verification succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
