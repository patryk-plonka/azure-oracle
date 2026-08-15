"""Integration tests for the protected limitations search route."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from auth import hash_token
from main import app
from models import Limitation, Source, Token, User


def _add_limitation(
    db: Session,
    *,
    limitation_id: str,
    source: Source,
    service: str = "Azure Kubernetes Service",
    feature: str = "Node pools",
    support_status: str = "supported",
    verification_state: str = "verified",
) -> Limitation:
    limitation = Limitation(
        id=limitation_id,
        source_id=source.id,
        service=service,
        feature=feature,
        support_status=support_status,
        limitation_type="service_limit",
        details=f"Details for {limitation_id}",
        quote=f"Source-backed quote for {limitation_id}.",
        workaround=None,
        confidence="high",
        verification_state=verification_state,
        verified_at=datetime.now(UTC),
    )
    db.add(limitation)
    return limitation


def test_search_requires_a_token(clean_test_database):
    client = TestClient(app, base_url="http://localhost")

    response = client.get("/limitations/search", params={"q": "AKS"})

    assert response.status_code == 401


def test_search_rejects_an_expired_token(auth_db_session: Session, seeded_user: User):
    raw = "expired-search-token-32-bytes!!"
    auth_db_session.add(
        Token(
            user_id=seeded_user.id,
            token_hash=hash_token(raw),
            name="expired",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    auth_db_session.commit()

    client = TestClient(app, base_url="http://localhost")
    response = client.get(
        "/limitations/search",
        params={"q": "AKS"},
        headers={"Authorization": f"Bearer {raw}"},
    )

    assert response.status_code == 401


def test_search_rejects_an_inactive_license(
    auth_db_session: Session, seeded_user_inactive_license: User
):
    raw = "inactive-search-token-32-bytes!"
    auth_db_session.add(
        Token(
            user_id=seeded_user_inactive_license.id,
            token_hash=hash_token(raw),
            name="default",
            expires_at=datetime.now(UTC) + timedelta(days=90),
        )
    )
    auth_db_session.commit()

    client = TestClient(app, base_url="http://localhost")
    response = client.get(
        "/limitations/search",
        params={"q": "AKS"},
        headers={"Authorization": f"Bearer {raw}"},
    )

    assert response.status_code == 403


def test_search_rejects_an_active_non_demo_license(
    auth_db_session: Session, seeded_user_active_non_demo_license: User
):
    raw = "active-non-demo-search-token!!!"
    auth_db_session.add(
        Token(
            user_id=seeded_user_active_non_demo_license.id,
            token_hash=hash_token(raw),
            name="default",
            expires_at=datetime.now(UTC) + timedelta(days=90),
        )
    )
    auth_db_session.commit()

    response = TestClient(app, base_url="http://localhost").get(
        "/limitations/search",
        params={"q": "AKS"},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert response.status_code == 403


def test_search_returns_matched_records_and_echoes_query_context(
    auth_db_session: Session, seeded_token: tuple[str, Token]
):
    source = Source(
        url="https://learn.microsoft.com/aks-limit",
        title="AKS limitation",
        source_type="documentation",
    )
    auth_db_session.add(source)
    auth_db_session.flush()
    auth_db_session.add(
        Limitation(
            id="aks-search-record",
            source_id=source.id,
            service="Azure Kubernetes Service",
            feature="Node pools",
            support_status="not_supported",
            limitation_type="service_limit",
            details="Test limitation",
            quote="A verified AKS limitation.",
            workaround=None,
            confidence="high",
            verification_state="verified",
            verified_at=datetime.now(UTC),
        )
    )
    auth_db_session.commit()
    raw, _ = seeded_token

    client = TestClient(app, base_url="http://localhost")
    response = client.get(
        "/limitations/search",
        params={"q": "AKS", "region": "westeurope", "sku": "Standard"},
        headers={"Authorization": f"Bearer {raw}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "query": {
            "q": "AKS",
            "region": "westeurope",
            "sku": "Standard",
            "note": "Region and SKU are echoed but not applied as filters in v1.",
        },
        "support_status": "unsupported",
        "record_count": 1,
        "records": [
            {
                "id": "aks-search-record",
                "service": "Azure Kubernetes Service",
                "feature": "Node pools",
                "support_status": "not_supported",
                "limitation_type": "service_limit",
                "details": "Test limitation",
                "workaround": None,
                "source_url": "https://learn.microsoft.com/aks-limit",
                "source_title": "AKS limitation",
                "quote": "A verified AKS limitation.",
                "confidence": "high",
                "verification_state": "verified",
                "verified_at": response.json()["records"][0]["verified_at"],
                "first_seen": None,
                "last_seen": None,
            }
        ],
    }


def test_search_returns_complete_provenance_for_every_matched_record(
    auth_db_session: Session, seeded_token: tuple[str, Token]
):
    first_source = Source(
        url="https://learn.microsoft.com/aks/first",
        title="First AKS source",
        source_type="documentation",
    )
    second_source = Source(
        url="https://learn.microsoft.com/aks/second",
        title="Second AKS source",
        source_type="documentation",
    )
    auth_db_session.add_all([first_source, second_source])
    auth_db_session.flush()
    _add_limitation(auth_db_session, limitation_id="aks-provenance-1", source=first_source)
    _add_limitation(auth_db_session, limitation_id="aks-provenance-2", source=first_source)
    _add_limitation(auth_db_session, limitation_id="aks-provenance-3", source=second_source)
    auth_db_session.commit()
    raw, _ = seeded_token

    client = TestClient(app, base_url="http://localhost")
    response = client.get(
        "/limitations/search",
        params={"q": "AKS"},
        headers={"Authorization": f"Bearer {raw}"},
    )

    assert response.status_code == 200
    records = response.json()["records"]
    assert len(records) == 3
    expected_rows = auth_db_session.scalars(
        select(Limitation)
        .options(joinedload(Limitation.source))
        .where(Limitation.id.in_([record["id"] for record in records]))
    ).all()
    expected_provenance = {
        row.id: {
            "source_url": row.source.url,
            "source_title": row.source.title,
            "quote": row.quote,
            "confidence": row.confidence,
            "verification_state": row.verification_state,
        }
        for row in expected_rows
    }

    for record in records:
        assert all(
            str(record[field]).strip()
            for field in (
                "source_url",
                "source_title",
                "quote",
                "confidence",
                "verification_state",
            )
        )
        assert {
            field: record[field]
            for field in (
                "source_url",
                "source_title",
                "quote",
                "confidence",
                "verification_state",
            )
        } == expected_provenance[record["id"]]


def test_search_excludes_unverified_records_from_records_and_verdict(
    auth_db_session: Session, seeded_token: tuple[str, Token]
):
    source = Source(
        url="https://learn.microsoft.com/aks/verification",
        title="AKS verification source",
        source_type="documentation",
    )
    auth_db_session.add(source)
    auth_db_session.flush()
    _add_limitation(
        auth_db_session,
        limitation_id="aks-verified-record",
        source=source,
        support_status="supported",
    )
    _add_limitation(
        auth_db_session,
        limitation_id="aks-unverified-record",
        source=source,
        support_status="not_supported",
        verification_state="unverified",
    )
    auth_db_session.commit()
    raw, _ = seeded_token

    client = TestClient(app, base_url="http://localhost")
    response = client.get(
        "/limitations/search",
        params={"q": "AKS"},
        headers={"Authorization": f"Bearer {raw}"},
    )

    assert response.status_code == 200
    assert [record["id"] for record in response.json()["records"]] == ["aks-verified-record"]
    assert response.json()["support_status"] == "supported"


def test_search_returns_a_clean_empty_result_when_nothing_matches(
    seeded_token: tuple[str, Token], clean_test_database: object
):
    raw, _ = seeded_token
    client = TestClient(app, base_url="http://localhost")

    response = client.get(
        "/limitations/search",
        params={"q": "zzz-nonexistent"},
        headers={"Authorization": f"Bearer {raw}"},
    )

    assert response.status_code == 200
    assert response.json()["records"] == []
    assert response.json()["record_count"] == 0
    assert response.json()["support_status"] == "supported"