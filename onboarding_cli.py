"""Safe client boundary for the interactive AzLimits onboarding command."""

from __future__ import annotations

import argparse
import getpass
import sys
import webbrowser
from collections.abc import Callable
from datetime import datetime
from urllib.parse import SplitResult, urlsplit

import httpx
from pydantic import BaseModel, ValidationError

from schemas import EulaAcceptanceResponse, EulaDocumentResponse, TokenCreateResponse

_TIMEOUT = httpx.Timeout(10.0)
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class OnboardingCliError(Exception):
    """A stable command-line failure that never includes sensitive request data."""


def _safe_error() -> OnboardingCliError:
    return OnboardingCliError("azlimits_onboarding_error: unable to complete onboarding safely.")


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


def run_onboarding(
    client: OnboardingApiClient,
    *,
    token_name: str | None = None,
    input_fn: Callable[[str], str] = input,
    hidden_input: Callable[[str], str] = getpass.getpass,
    output: Callable[[str], None] = print,
    browser_opener: Callable[[str], bool] = webbrowser.open,
    completion_handoff: Callable[[str, TokenCreateResponse], None] | None = None,
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

    output(f"EULA version: {eula.version}")
    output(eula.content)
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

    try:
        token = client.create_token(acceptance.issuance_credential, selected_name)
    except OnboardingCliError as error:
        output(str(error))
        output("Restart onboarding; token creation may already have consumed the credential.")
        return False

    if completion_handoff is not None:
        completion_handoff(token.token, token)
    _print_completion(output, token)
    return True


def _print_completion(output: Callable[[str], None], token: TokenCreateResponse) -> None:
    """Report safe token metadata; the raw token stays inside the process."""
    expires_at: datetime = token.expires_at
    output(f"Created API token '{token.name}' that expires at {expires_at.isoformat()}.")
    output("Keep the raw token private; it is not displayed by this command.")


def main(argv: list[str] | None = None) -> int:
    """Run interactive browser-based onboarding."""
    args = build_parser().parse_args(argv)
    try:
        client = OnboardingApiClient(args.api_base_url)
    except OnboardingCliError as error:
        print(error, file=sys.stderr)
        return 1
    return 0 if run_onboarding(client, token_name=args.token_name) else 1


if __name__ == "__main__":
    raise SystemExit(main())