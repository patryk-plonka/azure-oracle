"""Integration tests for the protected limitations search route."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from auth import hash_token
from main import app
from models import Limitation, Source, Token, User


def test_search_requires_a_token():
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