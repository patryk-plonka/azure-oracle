"""Safe REST client boundary for the local AzLimits MCP server."""

from __future__ import annotations

import os
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from mcp.server import MCPServer
from mcp_types import CallToolResult, TextContent
from pydantic import Field, ValidationError

from schemas import SearchResponse

_API_BASE_URL_ENV = "AZLIMITS_API_BASE_URL"
_API_TOKEN_ENV = "AZLIMITS_API_TOKEN"
_SEARCH_PATH = "/limitations/search"
_TIMEOUT = httpx.Timeout(10.0)


class AzLimitsMcpError(Exception):
    """Base class for safe, stable MCP-facing failures."""


class AzLimitsConfigurationError(AzLimitsMcpError):
    """Raised when the MCP process lacks a usable configuration."""


class AzLimitsAuthenticationError(AzLimitsMcpError):
    """Raised when the API rejects the configured token."""


class AzLimitsLicenseError(AzLimitsMcpError):
    """Raised when the configured token lacks an active Demo license."""


class AzLimitsUpstreamUnavailableError(AzLimitsMcpError):
    """Raised when the REST API cannot provide a valid response safely."""


def _configuration_error() -> AzLimitsConfigurationError:
    return AzLimitsConfigurationError(
        "azlimits_configuration_error: configure the MCP API URL and token."
    )


def _validate_base_url(value: str | None) -> str:
    if value is None or not value.strip():
        raise _configuration_error()

    base_url = value.strip()
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise _configuration_error()
    return base_url.rstrip("/")


def _validate_token(value: str | None) -> str:
    if value is None or not value.strip():
        raise _configuration_error()
    return value.strip()


def _validate_search_input(
    q: str,
    region: str | None,
    sku: str | None,
) -> None:
    if not isinstance(q, str) or not 1 <= len(q) <= 200:
        raise AzLimitsUpstreamUnavailableError(
            "azlimits_upstream_unavailable: provide a valid search request."
        )
    for value in (region, sku):
        if value is not None and (not isinstance(value, str) or len(value) > 200):
            raise AzLimitsUpstreamUnavailableError(
                "azlimits_upstream_unavailable: provide a valid search request."
            )


class AzLimitsApiClient:
    """Forward typed search requests to the protected AzLimits REST endpoint."""

    def __init__(self, base_url: str | None, token: str | None) -> None:
        self._base_url = _validate_base_url(base_url)
        self._token = _validate_token(token)

    @classmethod
    def from_environment(cls) -> AzLimitsApiClient:
        """Build a client from the MCP process environment without disclosing values."""
        return cls(
            os.getenv(_API_BASE_URL_ENV),
            os.getenv(_API_TOKEN_ENV),
        )

    def search_limitations(
        self,
        q: str,
        region: str | None = None,
        sku: str | None = None,
    ) -> SearchResponse:
        """Return the validated protected search response, or a safe failure."""
        _validate_search_input(q, region, sku)
        params = {"q": q}
        if region is not None:
            params["region"] = region
        if sku is not None:
            params["sku"] = sku

        try:
            with httpx.Client(timeout=_TIMEOUT, follow_redirects=False) as client:
                response = client.get(
                    f"{self._base_url}{_SEARCH_PATH}",
                    params=params,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
        except httpx.TimeoutException as error:
            raise AzLimitsUpstreamUnavailableError(
                "azlimits_upstream_unavailable: retry when the API is available."
            ) from error
        except httpx.HTTPError as error:
            raise AzLimitsUpstreamUnavailableError(
                "azlimits_upstream_unavailable: retry when the API is available."
            ) from error

        if response.status_code == 401:
            raise AzLimitsAuthenticationError(
                "azlimits_authentication_error: check the configured API token."
            )
        if response.status_code == 403:
            raise AzLimitsLicenseError(
                "azlimits_license_error: check the active Demo license."
            )
        if response.status_code != 200:
            raise AzLimitsUpstreamUnavailableError(
                "azlimits_upstream_unavailable: retry when the API is available."
            )

        try:
            return SearchResponse.model_validate(response.json())
        except (ValidationError, ValueError) as error:
            raise AzLimitsUpstreamUnavailableError(
                "azlimits_upstream_unavailable: retry when the API is available."
            ) from error


mcp = MCPServer(
    "azlimits",
    title="AzLimits",
    description="Search known, verified Azure limitation records with source evidence.",
)


def _tool_error(error: AzLimitsMcpError) -> CallToolResult:
    """Return a safe tool error without exposing upstream response details."""
    return CallToolResult(
        content=[TextContent(type="text", text=str(error))],
        is_error=True,
    )


def _tool_success(result: SearchResponse) -> CallToolResult:
    """Return the complete validated REST contract as structured MCP content."""
    structured_content = result.model_dump(mode="json")
    return CallToolResult(
        content=[TextContent(type="text", text=result.model_dump_json())],
        structured_content=structured_content,
    )


@mcp.tool(
    description=(
        "Return known, verified Azure limitation records and a support-status verdict "
        "with source evidence. An empty result does not prove that no limitation exists."
    )
)
def search_limitations(
    q: Annotated[str, Field(min_length=1, max_length=200)],
    region: Annotated[str | None, Field(max_length=200)] = None,
    sku: Annotated[str | None, Field(max_length=200)] = None,
) -> CallToolResult:
    """Search the protected AzLimits REST API without accepting credentials as inputs."""
    try:
        return _tool_success(AzLimitsApiClient.from_environment().search_limitations(q, region, sku))
    except AzLimitsMcpError as error:
        # MCP v2 wraps raised tool exceptions with its own prefix. Return the already
        # safe result directly so callers can reliably identify the stable error code.
        return _tool_error(error)


if __name__ == "__main__":
    mcp.run()
