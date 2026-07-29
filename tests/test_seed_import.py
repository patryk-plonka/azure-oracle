import csv
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, joinedload

from models import Limitation, Source
from seed import SeedValidationError, import_seed, read_seed_records

SEED_CSV = Path("concept/azure_limitations_db.csv")


def _counts(session: Session) -> tuple[int, int]:
    return (
        session.scalar(select(func.count()).select_from(Source)) or 0,
        session.scalar(select(func.count()).select_from(Limitation)) or 0,
    )


def _run_migration(test_engine: Engine, revision: str) -> None:
    config = Config("alembic.ini")
    with test_engine.connect() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, revision)


def test_import_retains_csv_rows_provenance_and_verification(clean_test_database: Engine) -> None:
    expected_records = read_seed_records(SEED_CSV)

    with Session(clean_test_database) as session:
        source_count, limitation_count = import_seed(SEED_CSV, session)
        limitations = session.scalars(select(Limitation).options(joinedload(Limitation.source))).all()

    assert limitation_count == len(expected_records)
    assert source_count == len({record.source_url for record in expected_records})
    assert len(limitations) == len(expected_records)
    assert all(
        limitation.source.url
        and limitation.source.title
        and limitation.quote
        and limitation.confidence
        and limitation.verification_state == "verified"
        and limitation.verified_at is not None
        for limitation in limitations
    )


def test_import_is_idempotent_and_deduplicates_sources(clean_test_database: Engine) -> None:
    with Session(clean_test_database) as session:
        first_counts = import_seed(SEED_CSV, session)
        second_counts = import_seed(SEED_CSV, session)
        persisted_counts = _counts(session)

    assert second_counts == first_counts
    assert persisted_counts == first_counts


def test_malformed_csv_rolls_back_entire_import(
    clean_test_database: Engine, tmp_path: Path
) -> None:
    malformed_csv = tmp_path / "malformed.csv"
    with SEED_CSV.open(newline="", encoding="utf-8") as source_file:
        reader = csv.DictReader(source_file)
        rows = list(reader)
        fieldnames = reader.fieldnames
    assert fieldnames is not None
    rows[-1]["quote"] = ""
    with malformed_csv.open("w", newline="", encoding="utf-8") as destination_file:
        writer = csv.DictWriter(destination_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with Session(clean_test_database) as session:
        import_seed(SEED_CSV, session)
        before_counts = _counts(session)
        with pytest.raises(SeedValidationError, match="quote must not be blank"):
            import_seed(malformed_csv, session)
        assert _counts(session) == before_counts


def test_migrations_recreate_an_empty_database_that_can_seed(test_engine: Engine) -> None:
    _run_migration(test_engine, "base")
    with test_engine.connect() as connection:
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    with Session(test_engine) as session:
        source_count, limitation_count = import_seed(SEED_CSV, session)

    assert source_count > 0
    assert limitation_count == len(read_seed_records(SEED_CSV))