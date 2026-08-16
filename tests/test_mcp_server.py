from __future__ import annotations

import httpx
import pytest
import respx
from mcp.client import Client
from mcp_types import TextContent

from mcp_server import (
    AzLimitsApiClient,
    AzLimitsAuthenticationError,
    AzLimitsConfigurationError,
    AzLimitsLicenseError,
    AzLimitsUpstreamUnavailableError,
    mcp,
)
from schemas import SearchResponse

API_URL = "https://azlimits.example.test"
TOKEN = "mcp-test-token"
SEARCH_URL = f"{API_URL}/limitations/search"


def search_payload() -> dict[str, object]:
    return {
        "query": {"q": "AKS", "region": "westeurope", "sku": "standard"},
        "support_status": "supported_with_limits",
        "record_count": 1,
        "records": [
            {
                "id": "aks-node-limit",
                "service": "AKS",
                "feature": "Node pools",
                "support_status": "supported_with_limits",
                "limitation_type": "quota",
                "details": "A documented node limit applies.",
                "workaround": "Request more quota.",
                "source_url": "https://learn.microsoft.com/azure/aks/quotas-skus-regions",
                "source_title": "AKS quotas and limits",
                "quote": "The node limit depends on the selected SKU.",
                "confidence": "high",
                "verification_state": "verified",
                "verified_at": "2026-08-16T00:00:00Z",
                "first_seen": "2026-08-01",
                "last_seen": "2026-08-16",
            }
        ],
    }


def configured_client(monkeypatch: pytest.MonkeyPatch) -> AzLimitsApiClient:
    monkeypatch.setenv("AZLIMITS_API_BASE_URL", f"{API_URL}/")
    monkeypatch.setenv("AZLIMITS_API_TOKEN", TOKEN)
    return AzLimitsApiClient.from_environment()


@respx.mock
def test_search_forwards_authorized_query_and_preserves_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=search_payload()))

    result = configured_client(monkeypatch).search_limitations(
        "AKS", region="westeurope", sku="standard"
    )

    assert isinstance(result, SearchResponse)
    serialized = result.model_dump(mode="json")
    expected = search_payload()
    assert serialized["support_status"] == expected["support_status"]
    assert serialized["record_count"] == expected["record_count"]
    assert result.query.q == "AKS"
    assert result.query.region == "westeurope"
    assert result.query.sku == "standard"
    assert serialized["records"] == expected["records"]
    assert route.called
    assert route.call_count == 1
    request = route.calls.last.request
    assert dict(request.url.params) == {
        "q": "AKS",
        "region": "westeurope",
        "sku": "standard",
    }
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize(
    ("base_url", "token"),
    [
        (None, TOKEN),
        ("   ", TOKEN),
        ("not-a-url", TOKEN),
        (API_URL, None),
        (API_URL, "  "),
    ],
)
def test_invalid_configuration_fails_without_request(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str | None,
    token: str | None,
) -> None:
    monkeypatch.delenv("AZLIMITS_API_BASE_URL", raising=False)
    monkeypatch.delenv("AZLIMITS_API_TOKEN", raising=False)
    if base_url is not None:
        monkeypatch.setenv("AZLIMITS_API_BASE_URL", base_url)
    if token is not None:
        monkeypatch.setenv("AZLIMITS_API_TOKEN", token)

    with pytest.raises(AzLimitsConfigurationError) as raised:
        AzLimitsApiClient.from_environment()

    message = str(raised.value)
    assert message.startswith("azlimits_configuration_error:")
    assert TOKEN not in message
    assert API_URL not in message


@respx.mock
@pytest.mark.parametrize(
    ("status_code", "error_type", "error_code"),
    [
        (401, AzLimitsAuthenticationError, "azlimits_authentication_error:"),
        (403, AzLimitsLicenseError, "azlimits_license_error:"),
        (302, AzLimitsUpstreamUnavailableError, "azlimits_upstream_unavailable:"),
        (500, AzLimitsUpstreamUnavailableError, "azlimits_upstream_unavailable:"),
    ],
)
def test_safe_http_failures_do_not_disclose_response_data(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    error_type: type[Exception],
    error_code: str,
) -> None:
    response = httpx.Response(
        status_code,
        content=b"server-body-secret",
        headers={"Location": "https://redirect.example.test/private"},
    )
    respx.get(SEARCH_URL).mock(return_value=response)

    with pytest.raises(error_type) as raised:
        configured_client(monkeypatch).search_limitations("AKS")

    message = str(raised.value)
    assert message.startswith(error_code)
    assert TOKEN not in message
    assert "server-body-secret" not in message
    assert "redirect.example.test" not in message


@respx.mock
@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError("connection failed"), httpx.ReadTimeout("read timed out")],
)
def test_transport_failures_are_safe(
    monkeypatch: pytest.MonkeyPatch, error: httpx.HTTPError
) -> None:
    respx.get(SEARCH_URL).mock(side_effect=error)

    with pytest.raises(AzLimitsUpstreamUnavailableError) as raised:
        configured_client(monkeypatch).search_limitations("AKS")

    message = str(raised.value)
    assert message.startswith("azlimits_upstream_unavailable:")
    assert TOKEN not in message
    assert "connection failed" not in message
    assert "read timed out" not in message


@respx.mock
def test_invalid_success_payload_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"records": []}))

    with pytest.raises(AzLimitsUpstreamUnavailableError) as raised:
        configured_client(monkeypatch).search_limitations("AKS")

    assert str(raised.value).startswith("azlimits_upstream_unavailable:")


@respx.mock
def test_out_of_contract_input_does_not_issue_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=search_payload()))

    with pytest.raises(AzLimitsUpstreamUnavailableError) as raised:
        configured_client(monkeypatch).search_limitations("")

    assert str(raised.value).startswith("azlimits_upstream_unavailable:")
    assert not route.called


@pytest.mark.anyio
async def test_mcp_tool_schema_exposes_only_search_inputs() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()

    assert len(tools.tools) == 1
    tool = tools.tools[0]
    assert tool.name == "search_limitations"
    assert tool.input_schema["required"] == ["q"]
    assert set(tool.input_schema["properties"]) == {"q", "region", "sku"}
    assert "token" not in tool.input_schema["properties"]
    assert "authorization" not in tool.input_schema["properties"]
    assert "url" not in tool.input_schema["properties"]


@pytest.mark.anyio
@respx.mock
async def test_mcp_tool_returns_complete_structured_search_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=search_payload()))
    monkeypatch.setenv("AZLIMITS_API_BASE_URL", API_URL)
    monkeypatch.setenv("AZLIMITS_API_TOKEN", TOKEN)

    async with Client(mcp) as client:
        result = await client.call_tool("search_limitations", {"q": "AKS"})

    assert not result.is_error
    assert result.structured_content == SearchResponse.model_validate(search_payload()).model_dump(mode="json")
    request = route.calls.last.request
    assert dict(request.url.params) == {"q": "AKS"}


@pytest.mark.anyio
@respx.mock
@pytest.mark.parametrize(
    ("status_code", "error_code"),
    [
        (401, "azlimits_authentication_error:"),
        (403, "azlimits_license_error:"),
        (500, "azlimits_upstream_unavailable:"),
    ],
)
async def test_mcp_tool_returns_safe_client_failures(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    error_code: str,
) -> None:
    response = httpx.Response(status_code, content=b"server-body-secret")
    respx.get(SEARCH_URL).mock(return_value=response)
    monkeypatch.setenv("AZLIMITS_API_BASE_URL", API_URL)
    monkeypatch.setenv("AZLIMITS_API_TOKEN", TOKEN)

    async with Client(mcp) as client:
        result = await client.call_tool("search_limitations", {"q": "AKS"})

    assert result.is_error
    content = result.content[0]
    assert isinstance(content, TextContent)
    assert content.text.startswith(error_code)
    assert TOKEN not in content.text
    assert "server-body-secret" not in content.text
