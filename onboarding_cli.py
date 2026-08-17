"""Safe client boundary for the interactive AzLimits onboarding command."""

from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
import webbrowser
from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from urllib.parse import SplitResult, urlsplit

import httpx
from pydantic import BaseModel, ValidationError

from schemas import EulaAcceptanceResponse, EulaDocumentResponse, TokenCreateResponse

_TIMEOUT = httpx.Timeout(10.0)
_MAX_RESPONSE_BYTES = 1_048_576
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_TERMINAL_CONTROL_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class OnboardingCliError(Exception):
    """A stable command-line failure that never includes sensitive request data."""


class InteractiveStream(Protocol):
    """Minimal terminal capability required for the confidential reveal boundary."""

    def isatty(self) -> bool: ...

    def write(self, value: str) -> object: ...

    def flush(self) -> None: ...


class TerminalRevealHandoff:
    """Reveal a new token once through verified interactive terminal streams.

    The production CLI intentionally uses stdout for both ordinary guidance and
    the reveal destination; no ordinary output is emitted during ``reveal``.
    """

    def __init__(
        self,
        confirmation_input: InteractiveStream,
        reveal_output: InteractiveStream,
        confirmation_fn: Callable[[str], str] = input,
    ) -> None:
        self._confirmation_input = confirmation_input
        self._reveal_output = reveal_output
        self._confirmation_fn = confirmation_fn

    def is_interactive(self) -> bool:
        """Require both the approval input and secret destination to be terminals."""
        return self._confirmation_input.isatty() and self._reveal_output.isatty()

    def confirm(self) -> bool:
        """Collect the explicit consent required before irreversible issuance."""
        try:
            response = self._confirmation_fn(
                "Reveal the new token once now? Type reveal to continue: "
            )
        except (EOFError, KeyboardInterrupt):
            return False
        return response.strip().lower() == "reveal"

    def reveal(self, raw_token: str) -> None:
        """Write and flush the raw token only to the isolated reveal stream."""
        self._reveal_output.write(f"{raw_token}\n")
        self._reveal_output.flush()


def _safe_error() -> OnboardingCliError:
    return OnboardingCliError("azlimits_onboarding_error: unable to complete onboarding safely.")


def _safe_terminal_text(value: str) -> str:
    """Remove terminal control sequences from server- or user-controlled text."""
    return _TERMINAL_CONTROL_RE.sub("", value)


def _parse_origin(value: str) -> SplitResult:
    """Validate an API origin without exposing a rejected value in errors."""
    candidate = value.strip()
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as error:
        raise _safe_error() from error

    if (
        not candidate
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or (parsed.scheme == "http" and hostname.lower() not in _LOOPBACK_HOSTS)
    ):
        raise _safe_error()
    return parsed


def validate_api_base_url(value: str) -> str:
    """Return a normalized safe API origin for onboarding requests."""
    parsed = _parse_origin(value)
    return parsed.geturl().rstrip("/")


def _validate_credential(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _safe_error()
    return value.strip()


class OnboardingApiClient:
    """Call the existing onboarding REST endpoints without logging credentials."""

    def __init__(self, base_url: str) -> None:
        self.base_url = validate_api_base_url(base_url)

    @property
    def login_url(self) -> str:
        return f"{self.base_url}/auth/login"

    def open_login(self, opener: Callable[[str], bool] = webbrowser.open) -> None:
        if not opener(self.login_url):
            raise _safe_error()

    def get_eula(self, onboarding_credential: str) -> EulaDocumentResponse:
        return self._request_model(
            "GET",
            "/auth/eula",
            onboarding_credential,
            None,
            EulaDocumentResponse,
        )

    def accept_eula(
        self, onboarding_credential: str, version: str
    ) -> EulaAcceptanceResponse:
        return self._request_model(
            "POST",
            "/auth/eula/accept",
            onboarding_credential,
            {"version": version},
            EulaAcceptanceResponse,
        )

    def create_token(self, issuance_credential: str, name: str) -> TokenCreateResponse:
        return self._request_model(
            "POST",
            "/auth/tokens",
            issuance_credential,
            {"name": name},
            TokenCreateResponse,
        )

    def _request_model[T: BaseModel](
        self,
        method: str,
        path: str,
        credential: str,
        payload: dict[str, str] | None,
        model: type[T],
    ) -> T:
        """Send one bounded request and safely validate a successful response."""
        try:
            with httpx.Client(timeout=_TIMEOUT, follow_redirects=False) as client:
                response = client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers={"Authorization": f"Bearer {_validate_credential(credential)}"},
                    json=payload,
                )
        except httpx.HTTPError as error:
            raise _safe_error() from error

        if response.is_redirect or not response.is_success:
            raise _safe_error()
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                if int(content_length) > _MAX_RESPONSE_BYTES:
                    raise _safe_error()
            except ValueError as error:
                raise _safe_error() from error
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise _safe_error()

        try:
            return model.model_validate(response.json())
        except (ValidationError, ValueError) as error:
            raise _safe_error() from error


def build_parser() -> argparse.ArgumentParser:
    """Build the non-secret command-line interface."""
    parser = argparse.ArgumentParser(description="Start AzLimits API onboarding.")
    parser.add_argument("--api-base-url", required=True, help="HTTPS API origin, or loopback HTTP origin.")
    parser.add_argument("--token-name", help="Optional name for the API token.")
    return parser


def _read_affirmative_confirmation(
    input_fn: Callable[[str], str], output: Callable[[str], None]
) -> bool:
    try:
        response = input_fn("Accept these terms? Type yes to continue: ")
    except (EOFError, KeyboardInterrupt):
        output("Onboarding cancelled before EULA acceptance.")
        return False
    return response.strip().lower() == "yes"


def _read_token_name(
    supplied_name: str | None, input_fn: Callable[[str], str]
) -> str | None:
    if supplied_name is not None:
        return supplied_name.strip() or None
    try:
        name = input_fn("Name for this API token: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return name or None


def _confirm_terminal_reveal(
    handoff: TerminalRevealHandoff,
    output: Callable[[str], None],
) -> bool:
    """Validate the terminal boundary and separate consent before issuing a token."""
    if not handoff.is_interactive():
        output("Token creation requires interactive terminal input and output; no token was created.")
        return False

    output(
        "The new raw token will be displayed once in this terminal. Terminal scrollback, "
        "recordings, remote sessions, or screen sharing may retain it. Enter it immediately "
        "into your MCP host's hidden secret prompt or store."
    )
    if not handoff.confirm():
        output("Token reveal was not approved; no token was created.")
        return False
    return True


def run_onboarding(
    client: OnboardingApiClient,
    *,
    token_name: str | None = None,
    input_fn: Callable[[str], str] = input,
    hidden_input: Callable[[str], str] = getpass.getpass,
    output: Callable[[str], None] = print,
    browser_opener: Callable[[str], bool] = webbrowser.open,
    reveal_handoff: TerminalRevealHandoff | None = None,
) -> bool:
    """Run the consent-preserving onboarding sequence without exposing secrets."""
    try:
        client.open_login(browser_opener)
        output("Complete GitHub consent in the browser.")
        onboarding_credential = hidden_input(
            "Paste the callback onboarding credential (hidden): "
        )
        eula = client.get_eula(_validate_credential(onboarding_credential))
    except (EOFError, KeyboardInterrupt):
        output("Onboarding cancelled before EULA acceptance.")
        return False
    except OnboardingCliError as error:
        output(str(error))
        return False

    output(f"EULA version: {_safe_terminal_text(eula.version)}")
    output(_safe_terminal_text(eula.content))
    if not _read_affirmative_confirmation(input_fn, output):
        output("Terms were not accepted; no token was created.")
        return False

    try:
        acceptance = client.accept_eula(onboarding_credential, eula.version)
    except OnboardingCliError as error:
        output(str(error))
        output("Restart onboarding; EULA acceptance may already have consumed the credential.")
        return False

    selected_name = _read_token_name(token_name, input_fn)
    if selected_name is None:
        output("Onboarding cancelled before token creation.")
        return False

    if reveal_handoff is None:
        output("Token creation requires an interactive terminal reveal; no token was created.")
        return False
    if not _confirm_terminal_reveal(reveal_handoff, output):
        return False

    try:
        token = client.create_token(acceptance.issuance_credential, selected_name)
    except OnboardingCliError as error:
        output(str(error))
        output("Restart onboarding; token creation may already have consumed the credential.")
        return False

    try:
        reveal_handoff.reveal(token.token)
    except (OSError, ValueError):
        output(
            "The one-time token may have been issued but could not be displayed safely. "
            "It cannot be recovered by this command; restart onboarding to create a new token."
        )
        return False
    _print_completion(output, client.base_url, token)
    return True


def _print_completion(
    output: Callable[[str], None], api_base_url: str, token: TokenCreateResponse
) -> None:
    """Report safe host-setup guidance without rendering the raw API token."""
    expires_at: datetime = token.expires_at
    output(
        f"Created API token '{_safe_terminal_text(token.name)}' that expires at "
        f"{expires_at.isoformat()}."
    )
    output("Keep the raw token private after its one-time terminal display.")
    output(
        "Enter the one-time token directly into your MCP host's approved hidden secret "
        "prompt or store. Do not put it in shell history, tool calls, committed files, "
        ".env files, or normal terminal input."
    )
    output("VS Code user-level MCP configuration template (placeholders only):")
    template = {
        "inputs": [
            {
                "id": "azlimits-api-token",
                "type": "promptString",
                "description": "AzLimits API token",
                "password": True,
            }
        ],
        "servers": {
            "azlimits": {
                "type": "stdio",
                "command": "uv",
                "args": ["run", "python", "mcp_server.py"],
                "cwd": "<repository-directory>",
                "env": {
                    "AZLIMITS_API_BASE_URL": api_base_url,
                    "AZLIMITS_API_TOKEN": "${input:azlimits-api-token}",
                },
            }
        },
    }
    output(json.dumps(template, indent=2))
    output(
        "For another MCP host, launch `uv run python mcp_server.py` as a local stdio "
        "server and supply only AZLIMITS_API_BASE_URL plus the raw token through that "
        "host's approved secret mechanism. Interactive secret inputs are host-specific."
    )
    output(
        "This standalone CLI cannot configure an already-running PowerShell, VS Code, "
        "or other parent process."
    )


def main(argv: list[str] | None = None) -> int:
    """Run interactive browser-based onboarding."""
    args = build_parser().parse_args(argv)
    try:
        client = OnboardingApiClient(args.api_base_url)
    except OnboardingCliError as error:
        print(error, file=sys.stderr)
        return 1
    return (
        0
        if run_onboarding(
            client,
            token_name=args.token_name,
            reveal_handoff=TerminalRevealHandoff(sys.stdin, sys.stderr),
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())