"""Contract tests binding the canonical AzLimits skill to the live MCP surface.

The skill is agent instruction, not application code, so these tests assert semantic
invariants - vocabulary, ordering, scope, and decision policy - rather than prose.
Wherever a fact also lives in the application, it is derived from the application
constant or the live MCP tool schema so the two cannot drift apart silently.
"""

from __future__ import annotations

import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path, PurePosixPath

import anyio
import pytest
import yaml
from mcp.client import Client

from mcp_server import mcp
from query import SUPPORT_STATUS_VERDICTS
from schemas import LimitationRecord, QueryContext, SearchResponse

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SKILL = REPO_ROOT / ".agents" / "skills" / "azlimits" / "SKILL.md"

# Every client discovers the one canonical directory through a relative symlink; a copy
# would silently fork the instructions the next time only one path is edited.
CLIENT_ALIASES = (".github/skills/azlimits", ".codex/skills/azlimits", ".claude/skills/azlimits")
EXPECTED_LINK_TARGET = PurePosixPath("../../.agents/skills/azlimits")
SYMLINK_MODE = "120000"

SYMLINK_HINT = (
    "This usually means the checkout did not materialize Git symlinks: on Windows, "
    "`git config core.symlinks true` requires Developer Mode or the "
    "SeCreateSymbolicLinkPrivilege. Re-enable symlinks and re-check out the path. "
    "Do not replace the alias with a copied directory."
)

# Stable failure classes are owned by the MCP adapter; read them from it rather than
# restating a second hard-coded contract here.
# Anchored to the emission shape ("azlimits_x: ...") rather than to any lowercase
# azlimits_* symbol, so a future helper or docstring cannot join the error contract.
ERROR_CODES = frozenset(
    re.findall(r'"(azlimits_[a-z_]+):', (REPO_ROOT / "mcp_server.py").read_text(encoding="utf-8"))
)

# Setup, repository-development, and credential-handling material must stay out of a
# skill that assumes onboarding and MCP configuration are already complete.
OUT_OF_SCOPE_MARKERS = (
    "git clone",
    "pip install",
    "uv run",
    "uv sync",
    "pytest",
    "alembic",
    "docker",
    "uvicorn",
    "azlimits-onboard",
    "mcp_server.py",
    "DATABASE_URL",
    "AZLIMITS_API_TOKEN",
    "AZLIMITS_API_BASE_URL",
)

# Words appearing in the skill's Title-case service query examples. Only consulted for
# non-lowercase tokens, so it never masks a real lower snake case identifier.
PROSE_EXAMPLE_WORDS = frozenset(
    {"azure", "kubernetes", "service", "firewall", "blob", "storage", "sftp"}
)

CREDENTIAL_SHAPES = (
    r"Bearer\s+\S",
    r"Authorization\s*:",
    r"\btokens?\s*[=:]\s*\S",
    r"\bghp_\w",
    r"\bsk-\w",
)


def _split_skill(path: Path) -> tuple[dict[str, str], str]:
    raw = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.DOTALL)
    assert match is not None, f"{path} must open with a YAML frontmatter block."
    loaded = yaml.safe_load(match.group(1))
    assert isinstance(loaded, dict), f"{path} frontmatter must be a mapping."
    return {str(key): str(value) for key, value in loaded.items()}, match.group(2)


def flatten(text: str) -> str:
    """Collapse whitespace so phrase assertions survive an editorial re-wrap."""
    return re.sub(r"\s+", " ", text)


FRONTMATTER, BODY = _split_skill(CANONICAL_SKILL)
FLAT_BODY = flatten(BODY)


@lru_cache(maxsize=1)
def live_tool_contract() -> tuple[frozenset[str], frozenset[str]]:
    """Return the tool names and input names actually exposed by the MCP server."""

    async def fetch() -> tuple[frozenset[str], frozenset[str]]:
        async with Client(mcp) as client:
            listing = await client.list_tools()
        names = {tool.name for tool in listing.tools}
        inputs: set[str] = set()
        for tool in listing.tools:
            inputs.update(tool.input_schema["properties"])
        return frozenset(names), frozenset(inputs)

    return anyio.run(fetch)


def backticked_identifiers(text: str) -> set[str]:
    """Return the identifier-shaped tokens the skill presents as machine vocabulary.

    Tokenizes *inside* each backtick span rather than matching the span whole, so a
    span like `search_limitations(q, max_results)` cannot smuggle an invented input
    past the contract check. Every real identifier in this contract is lower snake
    case; the only other backtick spans are the Title-case service query examples, so
    a non-lowercase token is prose when it is a known example word and invented
    vocabulary otherwise. The stoplist is consulted only for non-lowercase tokens,
    which keeps legitimate fields such as `service` from being filtered out.
    """
    tokens: set[str] = set()
    for span in re.findall(r"`([^`]+)`", text):
        tokens.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", span))
    return {
        token
        for token in tokens
        if re.fullmatch(r"[a-z][a-z0-9_]*", token) or token.lower() not in PROSE_EXAMPLE_WORDS
    }


def policy_clause(term: str) -> str:
    section = re.search(r"\n## Decision Policy\n(.*?)(?=\n## |\Z)", BODY, re.DOTALL)
    assert section is not None, "The skill must contain a '## Decision Policy' section."
    clause = re.search(
        rf"\*\*{re.escape(term)}\*\*(.*?)(?=\n- \*\*|\Z)", section.group(1), re.DOTALL
    )
    assert clause is not None, f"The decision policy must cover the '{term}' outcome."
    return flatten(clause.group(1)).lower()


def test_frontmatter_is_portable_and_names_the_skill() -> None:
    assert FRONTMATTER["name"] == "azlimits"
    # Extra keys would be client-specific and reduce portability across the aliases.
    assert set(FRONTMATTER) == {"name", "description"}


@pytest.mark.parametrize(
    "trigger",
    ["azure", "production", "infrastructure-as-code", "generat", "modif", "review", "approv"],
)
def test_description_triggers_on_production_azure_iac_work(trigger: str) -> None:
    assert trigger in FRONTMATTER["description"].lower()


def test_skill_uses_only_the_live_tool_and_input_vocabulary() -> None:
    tool_names, tool_inputs = live_tool_contract()

    # Without these the loops below are no-ops on an empty surface, and this test would
    # pass green on exactly the regression it exists to catch.
    assert tool_names, "The MCP server exposes no tools."
    assert tool_inputs, "The MCP server exposes no tool inputs."

    for name in tool_names:
        assert f"`{name}`" in BODY, f"The skill must name the live tool `{name}`."
    for input_name in tool_inputs:
        assert f"`{input_name}`" in BODY, f"The skill must name the live input `{input_name}`."


def test_skill_declares_no_vocabulary_outside_the_implemented_contract() -> None:
    tool_names, tool_inputs = live_tool_contract()
    allowed = (
        set(tool_names)
        | set(tool_inputs)
        | set(SearchResponse.model_fields)
        | set(QueryContext.model_fields)
        | set(LimitationRecord.model_fields)
        | set(SUPPORT_STATUS_VERDICTS.values())
        | set(ERROR_CODES)
    )

    declared = backticked_identifiers(BODY)
    assert declared, "No code vocabulary found in the skill; the subset check below is vacuous."

    unknown = declared - allowed
    assert not unknown, (
        f"The skill presents identifiers the implementation does not expose: {sorted(unknown)}. "
        "Speculative tools, inputs, fields, statuses, or error codes must not be invented."
    )


def test_record_count_is_read_before_the_aggregate_verdict() -> None:
    count_at = BODY.find("`record_count`")
    status_at = BODY.find("`support_status`")

    assert count_at != -1 and status_at != -1
    assert count_at < status_at, (
        "The skill must introduce `record_count` before `support_status`; the query core "
        "aggregates an empty result to 'supported', so the reverse order invites false approval."
    )


def test_zero_records_is_never_presented_as_proof_of_support() -> None:
    assert "no known matching record in the curated dataset" in FLAT_BODY
    assert re.search(r"(is not proof|does not prove|never proof)", FLAT_BODY, re.IGNORECASE)
    assert "inconclusive" in policy_clause("zero records")


def test_region_and_sku_are_documented_as_echoed_context_not_filters() -> None:
    note = QueryContext(q="AKS", region=None, sku=None).note

    assert note in FLAT_BODY, (
        "The skill must quote the v1 query note verbatim so it cannot drift from schemas.py."
    )


def test_every_provenance_field_survives_into_the_report() -> None:
    required = set(LimitationRecord.model_fields) - {"id"}

    missing = {field for field in required if f"`{field}`" not in BODY}
    assert not missing, f"The skill drops provenance fields from a finding: {sorted(missing)}"


def test_every_stable_error_class_is_handled_and_none_is_invented() -> None:
    declared = set(re.findall(r"\bazlimits_[a-z_]+\b", BODY))

    assert ERROR_CODES <= declared, f"Unhandled failure classes: {sorted(ERROR_CODES - declared)}"
    assert declared <= ERROR_CODES, f"Invented failure classes: {sorted(declared - ERROR_CODES)}"


def test_invalid_search_input_is_corrected_rather_than_retried_blindly() -> None:
    # Stop at the end of this bullet: it is the last one in its section, so without the
    # blank-line and heading terminators the clause would run to end of file and could be
    # satisfied by unrelated trailing prose.
    clause = re.search(
        r"`azlimits_upstream_unavailable`(.*?)(?=\n- `|\n\n|\n## |\Z)", BODY, re.DOTALL
    )
    assert clause is not None
    guidance = flatten(clause.group(1)).lower()

    assert "correct the query" in guidance
    assert "blind" in guidance, "Out-of-contract input must not lead to a blind retry."


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("unsupported", ("stop", "do not approve")),
        ("constrained", ("warn", "adapt")),
    ],
)
def test_decision_policy_blocks_unsupported_and_warns_on_constrained(
    term: str, expected: tuple[str, ...]
) -> None:
    clause = policy_clause(term)

    for phrase in expected:
        assert phrase in clause, f"The '{term}' policy must state '{phrase}'."


def test_supported_is_scoped_to_the_known_matching_records() -> None:
    clause = policy_clause("supported")

    assert "known matching records" in clause
    assert "not a guarantee" in clause


def test_inconclusive_outcomes_cannot_become_an_azlimits_validated_claim() -> None:
    assert re.search(r"never\b[^.]*azlimits-(validated|approved)", FLAT_BODY, re.IGNORECASE)
    assert "unvalidated" in FLAT_BODY.lower()


@pytest.mark.parametrize("marker", OUT_OF_SCOPE_MARKERS)
def test_skill_contains_no_setup_or_repository_development_instructions(marker: str) -> None:
    raw = CANONICAL_SKILL.read_text(encoding="utf-8").lower()

    assert marker.lower() not in raw, (
        f"'{marker}' belongs to onboarding or repository development, not the production skill."
    )


@pytest.mark.parametrize("pattern", CREDENTIAL_SHAPES)
def test_skill_contains_no_credential_shaped_example(pattern: str) -> None:
    raw = CANONICAL_SKILL.read_text(encoding="utf-8")

    assert not re.search(pattern, raw, re.IGNORECASE)


@lru_cache(maxsize=1)
def git_index_modes() -> dict[str, str]:
    """Return the mode Git records for each client alias, keyed by repository path."""
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-s", "--", *CLIENT_ALIASES],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:  # pragma: no cover - no Git
        pytest.skip(f"Git is unavailable for index inspection: {error}")

    modes: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        metadata, _, path = line.partition("\t")
        modes[path.strip()] = metadata.split()[0]
    return modes


@pytest.mark.parametrize("alias", CLIENT_ALIASES)
def test_client_alias_is_a_real_symlink(alias: str) -> None:
    path = REPO_ROOT / alias

    assert path.exists(), f"{alias} is missing. {SYMLINK_HINT}"
    assert path.is_symlink(), (
        f"{alias} exists but is not a symlink, so it is a copy that will fork from the "
        f"canonical skill. {SYMLINK_HINT}"
    )


@pytest.mark.parametrize("alias", CLIENT_ALIASES)
def test_client_alias_targets_the_canonical_skill_relatively(alias: str) -> None:
    path = REPO_ROOT / alias
    # Without this guard os.readlink raises a bare OSError on the very checkout the
    # hint is written for, and the diagnosis is lost.
    if not path.is_symlink():
        pytest.fail(f"{alias} is not a symlink, so it has no link target. {SYMLINK_HINT}")

    link = PurePosixPath(os.readlink(path).replace("\\", "/"))

    assert link == EXPECTED_LINK_TARGET, (
        f"{alias} must point at {EXPECTED_LINK_TARGET} so the alias stays portable across "
        f"checkouts; it points at {link}."
    )


@pytest.mark.parametrize("alias", CLIENT_ALIASES)
def test_client_alias_resolves_to_the_canonical_skill(alias: str) -> None:
    resolved = (REPO_ROOT / alias).resolve()

    assert resolved == CANONICAL_SKILL.parent.resolve(), (
        f"{alias} resolves to {resolved} instead of the canonical skill directory. {SYMLINK_HINT}"
    )
    assert (resolved / "SKILL.md").read_text(encoding="utf-8") == CANONICAL_SKILL.read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("alias", CLIENT_ALIASES)
def test_git_records_each_client_alias_as_a_symlink(alias: str) -> None:
    mode = git_index_modes().get(alias)

    assert mode is not None, (
        f"Git does not track {alias}, so a fresh clone would not get the alias. Check that "
        f".gitignore allows the path and that the alias has been added."
    )
    assert mode == SYMLINK_MODE, (
        f"Git records {alias} with mode {mode} instead of {SYMLINK_MODE} (symlink). "
        f"{SYMLINK_HINT}"
    )
