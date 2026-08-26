import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from release_identity import ReleaseIdentityError, load_release_git_sha

FULL_GIT_SHA = "0123456789abcdef0123456789abcdef01234567"


def write_metadata(path: Path, metadata: object) -> None:
    path.write_text(json.dumps(metadata), encoding="utf-8")


def test_load_release_git_sha_returns_configured_sha(tmp_path: Path) -> None:
    metadata_path = tmp_path / "release.json"
    write_metadata(metadata_path, {"git_sha": FULL_GIT_SHA})

    assert load_release_git_sha(metadata_path) == FULL_GIT_SHA


def test_load_release_git_sha_returns_unknown_when_metadata_is_absent(tmp_path: Path) -> None:
    assert load_release_git_sha(tmp_path / "release.json") == "unknown"


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"git_sha": "01234567"},
        {"git_sha": FULL_GIT_SHA.upper()},
        {"git_sha": FULL_GIT_SHA, "branch": "main"},
        {"git_sha": 123},
        [FULL_GIT_SHA],
    ],
)
def test_load_release_git_sha_rejects_invalid_metadata(
    tmp_path: Path, metadata: object
) -> None:
    metadata_path = tmp_path / "release.json"
    write_metadata(metadata_path, metadata)

    with pytest.raises(ReleaseIdentityError):
        load_release_git_sha(metadata_path)


def test_load_release_git_sha_rejects_malformed_json(tmp_path: Path) -> None:
    metadata_path = tmp_path / "release.json"
    metadata_path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ReleaseIdentityError):
        load_release_git_sha(metadata_path)


def test_version_endpoint_is_public_minimal_and_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "RELEASE_GIT_SHA", FULL_GIT_SHA)
    client = TestClient(main.app, base_url="http://localhost")

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {"git_sha": FULL_GIT_SHA}
    assert response.headers["cache-control"] == "no-store"


def test_version_endpoint_reports_unknown_for_local_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "RELEASE_GIT_SHA", "unknown")
    client = TestClient(main.app, base_url="http://localhost")

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {"git_sha": "unknown"}
