from __future__ import annotations

import httpx
import pytest
import respx

from onboarding_cli import (
    OnboardingApiClient,
    OnboardingCliError,
    main,
    validate_api_base_url,
)
from schemas import EulaAcceptanceResponse, EulaDocumentResponse, TokenCreateResponse

API_URL = "https://azlimits.example.test"
ONBOARDING_CREDENTIAL = "onboarding-sentinel-credential"
ISSUANCE_CREDENTIAL = "issuance-sentinel-credential"
RAW_TOKEN = "raw-api-token-sentinel"
UPSTREAM_SECRET = "upstream-response-secret"


def test_validates_safe_api_origins() -> None:
    assert validate_api_base_url("https://azlimits.example.test/") == API_URL
    assert validate_api_base_url("http://localhost:8000/") == "http://localhost:8000"
    assert validate_api_base_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000"
    assert validate_api_base_url("http://[::1]:8000") == "http://[::1]:8000"


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        "not-a-url",
        "http://azlimits.example.test",
        "https://azlimits.example.test/path",
        "https://azlimits.example.test?query=value",
        "https://azlimits.example.test#fragment",
        "https://user:password@azlimits.example.test",
    ],
)
def test_rejects_unsafe_api_origins_before_effects(base_url: str) -> None:
    with pytest.raises(OnboardingCliError) as raised:
        OnboardingApiClient(base_url)

    message = str(raised.value)
    if base_url:
        assert base_url not in message
    assert "password" not in message


def test_opens_exact_login_url() -> None:
    opened: list[str] = []

    def opener(url: str) -> bool:
        opened.append(url)
        return True

    OnboardingApiClient(f"{API_URL}/").open_login(opener)

    assert opened == [f"{API_URL}/auth/login"]


def test_cli_rejects_remote_http_without_opening_browser(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr("onboarding_cli.webbrowser.open", lambda _: pytest.fail("browser opened"))

    assert main(["--api-base-url", "http://unsafe.example.test"]) == 1

    captured = capsys.readouterr()
    assert "unsafe.example.test" not in captured.err


def test_cli_help_has_no_secret_arguments(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--help"])

    assert raised.value.code == 0
    output = capsys.readouterr().out.lower()
    for forbidden in ("credential", "bearer", "oauth", "secret", "token-value"):
        assert forbidden not in output


@respx.mock
def test_typed_rest_methods_use_expected_requests() -> None:
    eula_route = respx.get(f"{API_URL}/auth/eula").mock(
        return_value=httpx.Response(200, json={"version": "demo-v1", "content": "Terms"})
    )
    accept_route = respx.post(f"{API_URL}/auth/eula/accept").mock(
        return_value=httpx.Response(
            200,
            json={
                "next_action": "create_token",
                "license": {
                    "license_type": "demo",
                    "is_active": True,
                    "created_at": "2026-08-16T00:00:00Z",
                },
                "issuance_credential": ISSUANCE_CREDENTIAL,
                "issuance_expires_at": "2026-08-16T00:05:00Z",
            },
        )
    )
    token_route = respx.post(f"{API_URL}/auth/tokens").mock(
        return_value=httpx.Response(
            200,
            json={
                "token": RAW_TOKEN,
                "token_id": "token-id",
                "name": "local-mcp",
                "expires_at": "2026-11-14T00:00:00Z",
            },
        )
    )

    client = OnboardingApiClient(API_URL)
    assert client.get_eula(ONBOARDING_CREDENTIAL) == EulaDocumentResponse(
        version="demo-v1", content="Terms"
    )
    assert client.accept_eula(ONBOARDING_CREDENTIAL, "demo-v1") == EulaAcceptanceResponse.model_validate(
        accept_route.calls.last.response.json()
    )
    assert client.create_token(ISSUANCE_CREDENTIAL, "local-mcp") == TokenCreateResponse.model_validate(
        token_route.calls.last.response.json()
    )

    assert eula_route.calls.last.request.headers["Authorization"] == f"Bearer {ONBOARDING_CREDENTIAL}"
    assert accept_route.calls.last.request.headers["Authorization"] == f"Bearer {ONBOARDING_CREDENTIAL}"
    assert accept_route.calls.last.request.content == b'{"version":"demo-v1"}'
    assert token_route.calls.last.request.headers["Authorization"] == f"Bearer {ISSUANCE_CREDENTIAL}"
    assert token_route.calls.last.request.content == b'{"name":"local-mcp"}'


@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"Location": "https://redirect.example.test/private"}),
        httpx.Response(500, content=UPSTREAM_SECRET.encode()),
        httpx.Response(200, json={"unexpected": UPSTREAM_SECRET}),
    ],
)
def test_unsafe_upstream_responses_are_non_disclosing(response: httpx.Response) -> None:
    respx.get(f"{API_URL}/auth/eula").mock(return_value=response)

    with pytest.raises(OnboardingCliError) as raised:
        OnboardingApiClient(API_URL).get_eula(ONBOARDING_CREDENTIAL)

    message = str(raised.value)
    for forbidden in (
        ONBOARDING_CREDENTIAL,
        ISSUANCE_CREDENTIAL,
        RAW_TOKEN,
        UPSTREAM_SECRET,
        "redirect.example.test",
    ):
        assert forbidden not in message


@respx.mock
def test_transport_failure_is_non_disclosing() -> None:
    respx.get(f"{API_URL}/auth/eula").mock(side_effect=httpx.ReadTimeout(UPSTREAM_SECRET))

    with pytest.raises(OnboardingCliError) as raised:
        OnboardingApiClient(API_URL).get_eula(ONBOARDING_CREDENTIAL)

    assert ONBOARDING_CREDENTIAL not in str(raised.value)
    assert UPSTREAM_SECRET not in str(raised.value)