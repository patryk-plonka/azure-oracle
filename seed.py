from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from database import create_database_engine
from models import Limitation, Source

MINIMUM_RECORD_COUNT = 93
REQUIRED_FIELDS = {
    "id",
    "service",
    "support_status",
    "limitation_type",
    "source_type",
    "source_url",
    "source_title",
    "quote",
    "confidence",
}
SUPPORTED_VALUES = {
    "support_status": {
        "deprecated",
        "known_issue",
        "not_supported",
        "partially_supported",
        "preview",
        "retired",
        "support_ticket_required",
        "supported",
    },
    "limitation_type": {
        "auth_restriction",
        "behavior",
        "compatibility",
        "error_code",
        "feature_gap",
        "feature_removed",
        "gated",
        "lifecycle",
        "network_restriction",
        "operation_restriction",
        "platform_limitation",
        "platform_restriction",
        "preview_only",
        "quota_limit",
        "recommendation",
        "region_restriction",
        "sku_restriction",
        "tooling",
    },
    "source_type": {
        "github_docs_repo",
        "github_repo_issue",
        "learn_docs",
        "learn_troubleshoot",
    },
    "confidence": {"high", "medium"},
}
OPTIONAL_FIELDS = {
    "feature",
    "condition",
    "details",
    "environment",
    "region",
    "sku_tier",
    "auth_mode",
    "network_mode",
    "workaround",
}
DATE_FIELDS = {"first_seen", "last_seen"}
EXPECTED_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS | DATE_FIELDS


class SeedValidationError(ValueError):
    """Raised when the curated CSV violates the v1 import contract."""


@dataclass(frozen=True)
class SeedRecord:
    id: str
    service: str
    feature: str | None
    support_status: str
    limitation_type: str
    condition: str | None
    details: str | None
    environment: str | None
    region: str | None
    sku_tier: str | None
    auth_mode: str | None
    network_mode: str | None
    source_type: str
    source_url: str
    source_title: str
    quote: str
    workaround: str | None
    confidence: str
    first_seen: date | None
    last_seen: date | None


def read_seed_records(csv_path: Path) -> list[SeedRecord]:
    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None or set(reader.fieldnames) != EXPECTED_FIELDS:
            raise SeedValidationError("CSV headers do not match the v1 seed contract.")
        rows = list(reader)

    if len(rows) < MINIMUM_RECORD_COUNT:
        raise SeedValidationError(f"CSV must contain at least {MINIMUM_RECORD_COUNT} records.")

    records: list[SeedRecord] = []
    seen_ids: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        normalized = {field: value.strip() for field, value in row.items()}
        row_id = normalized["id"] or f"row {row_number}"
        if row_id in seen_ids:
            raise SeedValidationError(f"Duplicate limitation ID: {row_id}.")
        seen_ids.add(row_id)

        for field in REQUIRED_FIELDS:
            if not normalized[field]:
                raise SeedValidationError(f"{row_id}: {field} must not be blank.")
        for field, allowed_values in SUPPORTED_VALUES.items():
            if normalized[field] not in allowed_values:
                raise SeedValidationError(f"{row_id}: unsupported {field} value.")

        parsed_dates = {
            field: _parse_date(normalized[field], row_id, field) for field in DATE_FIELDS
        }
        records.append(
            SeedRecord(
                id=normalized["id"],
                service=normalized["service"],
                feature=_optional(normalized["feature"]),
                support_status=normalized["support_status"],
                limitation_type=normalized["limitation_type"],
                condition=_optional(normalized["condition"]),
                details=_optional(normalized["details"]),
                environment=_optional(normalized["environment"]),
                region=_optional(normalized["region"]),
                sku_tier=_optional(normalized["sku_tier"]),
                auth_mode=_optional(normalized["auth_mode"]),
                network_mode=_optional(normalized["network_mode"]),
                source_type=normalized["source_type"],
                source_url=normalized["source_url"],
                source_title=normalized["source_title"],
                quote=normalized["quote"],
                workaround=_optional(normalized["workaround"]),
                confidence=normalized["confidence"],
                first_seen=parsed_dates["first_seen"],
                last_seen=parsed_dates["last_seen"],
            )
        )
    return records


def import_seed(csv_path: Path, session: Session) -> tuple[int, int]:
    records = read_seed_records(csv_path)
    imported_at = datetime.now(UTC)
    source_values = {
        record.source_url: {
            "url": record.source_url,
            "title": record.source_title,
            "source_type": record.source_type,
        }
        for record in records
    }

    with session.begin():
        session.execute(
            insert(Source)
            .values(list(source_values.values()))
            .on_conflict_do_update(
                index_elements=[Source.url],
                set_={
                    "title": insert(Source).excluded.title,
                    "source_type": insert(Source).excluded.source_type,
                },
            )
        )
        source_ids: dict[str, UUID] = {
            source_url: source_id
            for source_url, source_id in session.execute(select(Source.url, Source.id))
        }
        limitation_values = [
            {
                "id": record.id,
                "source_id": source_ids[record.source_url],
                "service": record.service,
                "feature": record.feature,
                "support_status": record.support_status,
                "limitation_type": record.limitation_type,
                "condition": record.condition,
                "details": record.details,
                "environment": record.environment,
                "region": record.region,
                "sku_tier": record.sku_tier,
                "auth_mode": record.auth_mode,
                "network_mode": record.network_mode,
                "quote": record.quote,
                "workaround": record.workaround,
                "confidence": record.confidence,
                "first_seen": record.first_seen,
                "last_seen": record.last_seen,
                "verification_state": "verified",
                "verified_at": imported_at,
            }
            for record in records
        ]
        session.execute(
            insert(Limitation)
            .values(limitation_values)
            .on_conflict_do_update(
                index_elements=[Limitation.id],
                set_={
                    column.name: getattr(insert(Limitation).excluded, column.name)
                    for column in Limitation.__table__.columns
                    if column.name not in {"id", "imported_at"}
                },
            )
        )
        source_count = session.scalar(select(func.count()).select_from(Source))
        limitation_count = session.scalar(select(func.count()).select_from(Limitation))

    return source_count or 0, limitation_count or 0


def _optional(value: str) -> str | None:
    return value or None


def _parse_date(value: str, row_id: str, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise SeedValidationError(f"{row_id}: {field} must be an ISO date.") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the curated AzLimits CSV seed.")
    parser.add_argument("csv_path", type=Path)
    arguments = parser.parse_args()

    engine = create_database_engine()
    with Session(engine) as session:
        source_count, limitation_count = import_seed(arguments.csv_path, session)
    print(f"Seed import complete: {source_count} sources, {limitation_count} limitations.")


if __name__ == "__main__":
    main()