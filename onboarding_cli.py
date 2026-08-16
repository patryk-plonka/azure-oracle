"""Safe client boundary for the interactive AzLimits onboarding command."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from collections.abc import Callable
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


def main(argv: list[str] | None = None) -> int:
    """Validate configuration and begin browser-based onboarding."""
    args = build_parser().parse_args(argv)
    try:
        OnboardingApiClient(args.api_base_url).open_login()
    except OnboardingCliError as error:
        print(error, file=sys.stderr)
        return 1
    print("Browser sign-in opened. Complete consent before continuing onboarding.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())