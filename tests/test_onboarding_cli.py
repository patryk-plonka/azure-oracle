from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import pytest
import respx

from onboarding_cli import (
    OnboardingApiClient,
    OnboardingCliError,
    TerminalRevealHandoff,
    main,
    run_onboarding,
    validate_api_base_url,
)
from schemas import EulaAcceptanceResponse, EulaDocumentResponse, TokenCreateResponse

API_URL = "https://azlimits.example.test"
ONBOARDING_CREDENTIAL = "onboarding-sentinel-credential"
ISSUANCE_CREDENTIAL = "issuance-sentinel-credential"
RAW_TOKEN = "raw-api-token-sentinel"
UPSTREAM_SECRET = "upstream-response-secret"


class FakeTerminalStream:
    def __init__(self, *, is_tty: bool = True, fail_write: bool = False) -> None:
        self.is_tty = is_tty
        self.fail_write = fail_write
        self.writes: list[str] = []
        self.flush_count = 0

    def isatty(self) -> bool:
        return self.is_tty

    def write(self, value: str) -> int:
        if self.fail_write:
            raise OSError("stream failure")
        self.writes.append(value)
        return len(value)

    def flush(self) -> None:
        if self.fail_write:
            raise OSError("flush failure")
        self.flush_count += 1


def _interactive_handoff(
    *, reveal_stream: FakeTerminalStream | None = None
) -> tuple[TerminalRevealHandoff, FakeTerminalStream]:
    stream = reveal_stream or FakeTerminalStream()
    return TerminalRevealHandoff(
        FakeTerminalStream(),
        stream,
        confirmation_fn=lambda _: "reveal",
    ), stream


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


def test_main_wires_production_reveal_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    handoff, reveal_stream = _interactive_handoff()
    client = OnboardingApiClient(API_URL)
    calls: list[str] = []

    monkeypatch.setattr("onboarding_cli.OnboardingApiClient", lambda _: client)
    monkeypatch.setattr("onboarding_cli.webbrowser.open", lambda _: True)
    monkeypatch.setattr("onboarding_cli.getpass.getpass", lambda _: ONBOARDING_CREDENTIAL)
    monkeypatch.setattr("onboarding_cli.sys.stdin", handoff._confirmation_input)
    monkeypatch.setattr("onboarding_cli.sys.stdout", reveal_stream)

    def fake_run_onboarding(received_client: OnboardingApiClient, **kwargs: object) -> bool:
        calls.append(type(kwargs["reveal_handoff"]).__name__)
        return received_client is client

    monkeypatch.setattr(
        "onboarding_cli.run_onboarding",
        fake_run_onboarding,
    )

    assert main(["--api-base-url", API_URL]) == 0
    assert calls == ["TerminalRevealHandoff"]


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


def _eula_response() -> httpx.Response:
    return httpx.Response(200, json={"version": "demo-v1", "content": "Terms"})


def _acceptance_response() -> httpx.Response:
    return httpx.Response(
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


def _token_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "token": RAW_TOKEN,
            "token_id": "token-id",
            "name": "local-mcp",
            "expires_at": "2026-11-14T00:00:00Z",
        },
    )


@respx.mock
def test_interactive_workflow_uses_hidden_credential_and_handoff() -> None:
    eula_route = respx.get(f"{API_URL}/auth/eula").mock(return_value=_eula_response())
    accept_route = respx.post(f"{API_URL}/auth/eula/accept").mock(
        return_value=_acceptance_response()
    )
    token_route = respx.post(f"{API_URL}/auth/tokens").mock(return_value=_token_response())
    opened: list[str] = []
    output: list[str] = []
    handoff, reveal_stream = _interactive_handoff()
    client = OnboardingApiClient(API_URL)

    def browser_opener(url: str) -> bool:
        opened.append(url)
        return True

    assert run_onboarding(
        client,
        input_fn=lambda prompt: "reveal" if "Reveal" in prompt else "yes",
        hidden_input=lambda _: ONBOARDING_CREDENTIAL,
        output=output.append,
        browser_opener=browser_opener,
        token_name="local-mcp",
        reveal_handoff=handoff,
    )

    assert opened == [f"{API_URL}/auth/login"]
    assert eula_route.calls.last.request.headers["Authorization"] == f"Bearer {ONBOARDING_CREDENTIAL}"
    assert accept_route.calls.last.request.content == b'{"version":"demo-v1"}'
    assert token_route.calls.last.request.headers["Authorization"] == f"Bearer {ISSUANCE_CREDENTIAL}"
    assert token_route.calls.last.request.content == b'{"name":"local-mcp"}'
    assert reveal_stream.writes == [f"{RAW_TOKEN}\n"]
    assert reveal_stream.flush_count == 1
    rendered = "\n".join(output)
    for secret in (ONBOARDING_CREDENTIAL, ISSUANCE_CREDENTIAL, RAW_TOKEN):
        assert secret not in rendered
    assert "EULA version: demo-v1" in rendered
    assert "Terms" in rendered


@respx.mock
def test_declined_eula_has_no_state_changing_requests() -> None:
    respx.get(f"{API_URL}/auth/eula").mock(return_value=_eula_response())
    accept_route = respx.post(f"{API_URL}/auth/eula/accept").mock(return_value=_acceptance_response())
    token_route = respx.post(f"{API_URL}/auth/tokens").mock(return_value=_token_response())
    client = OnboardingApiClient(API_URL)
    output: list[str] = []

    assert not run_onboarding(
        client,
        input_fn=lambda _: "no",
        hidden_input=lambda _: ONBOARDING_CREDENTIAL,
        output=output.append,
        browser_opener=lambda _: True,
    )

    assert accept_route.call_count == 0
    assert token_route.call_count == 0
    assert "no token was created" in "\n".join(output)


@respx.mock
@pytest.mark.parametrize(
    "status", [401, 403, 409, 500]
)
def test_eula_accept_failure_is_not_retried_and_requires_restart(status: int) -> None:
    respx.get(f"{API_URL}/auth/eula").mock(return_value=_eula_response())
    accept_route = respx.post(f"{API_URL}/auth/eula/accept").mock(
        return_value=httpx.Response(status, content=UPSTREAM_SECRET.encode())
    )
    client = OnboardingApiClient(API_URL)
    output: list[str] = []
    handoff, _ = _interactive_handoff()

    assert not run_onboarding(
        client,
        input_fn=lambda prompt: "reveal" if "Reveal" in prompt else "yes",
        hidden_input=lambda _: ONBOARDING_CREDENTIAL,
        output=output.append,
        browser_opener=lambda _: True,
        token_name="local-mcp",
        reveal_handoff=handoff,
    )

    assert accept_route.call_count == 1
    rendered = "\n".join(output)
    assert "Restart onboarding" in rendered
    for secret in (ONBOARDING_CREDENTIAL, ISSUANCE_CREDENTIAL, RAW_TOKEN, UPSTREAM_SECRET):
        assert secret not in rendered


@respx.mock
def test_token_timeout_is_not_retried_and_requires_restart() -> None:
    respx.get(f"{API_URL}/auth/eula").mock(return_value=_eula_response())
    respx.post(f"{API_URL}/auth/eula/accept").mock(return_value=_acceptance_response())
    token_route = respx.post(f"{API_URL}/auth/tokens").mock(
        side_effect=httpx.ReadTimeout(UPSTREAM_SECRET)
    )
    client = OnboardingApiClient(API_URL)
    output: list[str] = []
    handoff, _ = _interactive_handoff()

    assert not run_onboarding(
        client,
        input_fn=lambda prompt: "reveal" if "Reveal" in prompt else "yes",
        hidden_input=lambda _: ONBOARDING_CREDENTIAL,
        output=output.append,
        browser_opener=lambda _: True,
        token_name="local-mcp",
        reveal_handoff=handoff,
    )

    assert token_route.call_count == 1
    rendered = "\n".join(output)
    assert "Restart onboarding" in rendered
    assert ISSUANCE_CREDENTIAL not in rendered
    assert UPSTREAM_SECRET not in rendered


@respx.mock
def test_completion_guidance_is_secret_free_and_host_scoped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    respx.get(f"{API_URL}/auth/eula").mock(return_value=_eula_response())
    respx.post(f"{API_URL}/auth/eula/accept").mock(return_value=_acceptance_response())
    respx.post(f"{API_URL}/auth/tokens").mock(return_value=_token_response())
    output: list[str] = []
    handoff, _ = _interactive_handoff()
    monkeypatch.chdir(tmp_path)
    environment_before = dict(os.environ)
    argv_before = list(sys.argv)

    assert run_onboarding(
        OnboardingApiClient(API_URL),
        input_fn=lambda prompt: "reveal" if "Reveal" in prompt else "yes",
        hidden_input=lambda _: ONBOARDING_CREDENTIAL,
        output=output.append,
        browser_opener=lambda _: True,
        token_name="local-mcp",
        reveal_handoff=handoff,
    )

    assert dict(os.environ) == environment_before
    assert list(sys.argv) == argv_before
    assert list(tmp_path.rglob("*")) == []
    rendered = "\n".join(output)
    assert "uv run python mcp_server.py" in rendered
    assert '"AZLIMITS_API_BASE_URL": "https://azlimits.example.test"' in rendered
    assert '"AZLIMITS_API_TOKEN": "${input:azlimits-api-token}"' in rendered
    assert '"password": true' in rendered
    assert "already-running PowerShell, VS Code" in rendered
    for secret in (ONBOARDING_CREDENTIAL, ISSUANCE_CREDENTIAL, RAW_TOKEN):
        assert secret not in rendered
    for forbidden_operation in ("setx", "registry", "powershell assignment"):
        assert forbidden_operation not in rendered.lower()
    assert "Do not put it in shell history" in rendered
    assert ".env files" in rendered


@respx.mock
@pytest.mark.parametrize("response", ["no", EOFError(), KeyboardInterrupt()])
def test_reveal_rejection_prevents_token_issuance(response: str | BaseException) -> None:
    respx.get(f"{API_URL}/auth/eula").mock(return_value=_eula_response())
    respx.post(f"{API_URL}/auth/eula/accept").mock(return_value=_acceptance_response())
    token_route = respx.post(f"{API_URL}/auth/tokens").mock(return_value=_token_response())
    output: list[str] = []
    responses = iter(["yes", response])
    reveal_stream = FakeTerminalStream()

    def confirmation_fn(_: str) -> str:
        value = next(responses)
        if isinstance(value, BaseException):
            raise value
        return value

    handoff = TerminalRevealHandoff(
        FakeTerminalStream(), reveal_stream, confirmation_fn=confirmation_fn
    )

    def input_fn(_: str) -> str:
        value = next(responses)
        return value if isinstance(value, str) else "yes"

    assert not run_onboarding(
        OnboardingApiClient(API_URL),
        input_fn=input_fn,
        hidden_input=lambda _: ONBOARDING_CREDENTIAL,
        output=output.append,
        browser_opener=lambda _: True,
        token_name="local-mcp",
        reveal_handoff=handoff,
    )

    assert token_route.call_count == 0
    assert reveal_stream.writes == []
    assert RAW_TOKEN not in "\n".join(output)


@respx.mock
@pytest.mark.parametrize("input_is_tty,reveal_is_tty", [(False, True), (True, False)])
def test_noninteractive_reveal_boundary_prevents_token_issuance(
    input_is_tty: bool, reveal_is_tty: bool
) -> None:
    respx.get(f"{API_URL}/auth/eula").mock(return_value=_eula_response())
    respx.post(f"{API_URL}/auth/eula/accept").mock(return_value=_acceptance_response())
    token_route = respx.post(f"{API_URL}/auth/tokens").mock(return_value=_token_response())
    output: list[str] = []
    reveal_stream = FakeTerminalStream(is_tty=reveal_is_tty)
    handoff = TerminalRevealHandoff(FakeTerminalStream(is_tty=input_is_tty), reveal_stream)

    assert not run_onboarding(
        OnboardingApiClient(API_URL),
        input_fn=lambda prompt: "reveal" if "Reveal" in prompt else "yes",
        hidden_input=lambda _: ONBOARDING_CREDENTIAL,
        output=output.append,
        browser_opener=lambda _: True,
        token_name="local-mcp",
        reveal_handoff=handoff,
    )

    assert token_route.call_count == 0
    assert reveal_stream.writes == []
    assert RAW_TOKEN not in "\n".join(output)


@respx.mock
@pytest.mark.parametrize("failure", ["write", "flush"])
def test_reveal_failure_never_retries_or_discloses_token(failure: str) -> None:
    respx.get(f"{API_URL}/auth/eula").mock(return_value=_eula_response())
    respx.post(f"{API_URL}/auth/eula/accept").mock(return_value=_acceptance_response())
    token_route = respx.post(f"{API_URL}/auth/tokens").mock(return_value=_token_response())
    output: list[str] = []
    class FailingRevealStream(FakeTerminalStream):
        def write(self, value: str) -> int:
            if failure == "write":
                raise OSError("stream failure")
            return super().write(value)

        def flush(self) -> None:
            if failure == "flush":
                raise OSError("flush failure")
            super().flush()

    handoff, reveal_stream = _interactive_handoff(reveal_stream=FailingRevealStream())

    assert not run_onboarding(
        OnboardingApiClient(API_URL),
        input_fn=lambda prompt: "reveal" if "Reveal" in prompt else "yes",
        hidden_input=lambda _: ONBOARDING_CREDENTIAL,
        output=output.append,
        browser_opener=lambda _: True,
        token_name="local-mcp",
        reveal_handoff=handoff,
    )

    assert token_route.call_count == 1
    assert len(reveal_stream.writes) <= 1
    rendered = "\n".join(output)
    assert "cannot be recovered" in rendered
    assert RAW_TOKEN not in rendered


def test_operating_guide_documents_one_time_tty_reveal() -> None:
    guide = " ".join(Path("README.md").read_text(encoding="utf-8").split())

    for expected in (
        "type `reveal`",
        "interactive TTYs",
        "displayed exactly once",
        "Terminal scrollback, recordings, remote sessions, and screen sharing",
        "If the reveal is declined, cancelled",
        "the raw token cannot be recovered",
        '"AZLIMITS_API_TOKEN": "${input:azlimits-api-token}"',
        "cannot configure an already-running PowerShell, VS Code",
    ):
        assert expected in guide

    for forbidden in ("$env:AZLIMITS_API_TOKEN", "setx", "<retrieve-from-approved-secret-store>"):
        assert forbidden not in guide


def test_reveal_is_not_sent_through_generic_output() -> None:
    handoff, reveal_stream = _interactive_handoff()
    generic_output: list[str] = []

    assert handoff.is_interactive()
    assert handoff.confirm()
    handoff.reveal(RAW_TOKEN)

    assert generic_output == []
    assert reveal_stream.writes == [f"{RAW_TOKEN}\n"]