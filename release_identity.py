import json
import re
from pathlib import Path

UNKNOWN_GIT_SHA = "unknown"
RELEASE_METADATA_PATH = Path(__file__).resolve().parent / "release.json"
_FULL_GIT_SHA = re.compile(r"[0-9a-f]{40}")


class ReleaseIdentityError(ValueError):
    """Raised when generated release metadata is present but invalid."""


def load_release_git_sha(metadata_path: Path = RELEASE_METADATA_PATH) -> str:
    """Load the deployed Git SHA, with a safe fallback for local checkouts."""
    try:
        raw_metadata = metadata_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return UNKNOWN_GIT_SHA
    except (OSError, UnicodeError) as exc:
        raise ReleaseIdentityError("Release metadata could not be read.") from exc

    try:
        metadata: object = json.loads(raw_metadata)
    except json.JSONDecodeError as exc:
        raise ReleaseIdentityError("Release metadata must be valid JSON.") from exc

    if not isinstance(metadata, dict) or set(metadata) != {"git_sha"}:
        raise ReleaseIdentityError("Release metadata must contain exactly git_sha.")

    git_sha = metadata["git_sha"]
    if not isinstance(git_sha, str) or _FULL_GIT_SHA.fullmatch(git_sha) is None:
        raise ReleaseIdentityError("Release git_sha must be a full lowercase Git SHA.")

    return git_sha
