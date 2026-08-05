from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from query import (
    SERVICE_ALIASES,
    SUPPORT_STATUS_VERDICTS,
    aggregate_verdict,
    map_support_status,
    resolve_query,
)
from schemas import LimitationRecord, QueryContext, SearchResponse
from seed import SUPPORTED_VALUES


def test_resolve_query_normalizes_aks_aliases():
    expected_service = "Azure Kubernetes Service"

    assert resolve_query("AKS") == expected_service
    assert resolve_query("aks") == expected_service
    assert resolve_query(" AKS ") == expected_service
    assert resolve_query("kubernetes") == expected_service


def test_resolve_query_returns_none_for_unknown_alias():
    assert resolve_query("unknown service") is None


def test_aliases_cover_every_service_in_the_curated_corpus():
    assert set(SERVICE_ALIASES.values()) == {
        "ARM Templates",
        "Azure Blob Storage (SFTP)",
        "Azure Container Apps",
        "Azure Container Registry",
        "Azure Firewall",
        "Azure Functions",
        "Azure Kubernetes Service",
        "Azure Local",
        "Azure Management Groups",
        "Azure Networking",
        "Azure Resource Groups",
        "Azure Resource Manager",
        "Azure Site Recovery (Scout 8.0.1)",
        "Azure Subscriptions",
    }


def test_support_status_mapping_matches_the_seed_vocabulary():
    assert set(SUPPORT_STATUS_VERDICTS) == SUPPORTED_VALUES["support_status"]
    assert map_support_status("future_status") == "constrained"


def test_aggregate_verdict_uses_severity_precedence():
    assert aggregate_verdict(
        map_support_status(status)
        for status in ("not_supported", "known_issue", "supported", "partially_supported")
    ) == "unsupported"
    assert aggregate_verdict(map_support_status(status) for status in ("known_issue", "supported")) == (
        "constrained"
    )
    assert aggregate_verdict(map_support_status(status) for status in ("supported", "supported")) == (
        "supported"
    )
    assert aggregate_verdict([]) == "supported"


def test_search_response_requires_provenance_and_explains_unapplied_filters():
    record = LimitationRecord(
        id="lim-1",
        service="Azure Kubernetes Service",
        feature=None,
        support_status="supported",
        limitation_type="quota_limit",
        details=None,
        workaround=None,
        source_url="https://example.test/source",
        source_title="Source title",
        quote="A source-backed limitation.",
        confidence="high",
        verification_state="verified",
        verified_at=datetime.now(UTC),
        first_seen=None,
        last_seen=None,
    )
    response = SearchResponse(
        query=QueryContext(q="AKS", region="westeurope", sku="Standard"),
        support_status="supported",
        record_count=1,
        records=[record],
    )

    assert response.query.note == "Region and SKU are echoed but not applied as filters in v1."
    assert response.model_dump()["records"][0]["source_url"] == "https://example.test/source"

    record_data = record.model_dump(exclude={"quote"})
    with pytest.raises(ValidationError):
        LimitationRecord(**record_data)
