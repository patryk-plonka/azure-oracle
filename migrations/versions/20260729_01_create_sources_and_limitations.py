"""create sources and limitations

Revision ID: 20260729_01
Revises:
Create Date: 2026-07-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url"),
    )
    op.create_table(
        "limitations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("service", sa.String(length=255), nullable=False),
        sa.Column("feature", sa.Text(), nullable=True),
        sa.Column("support_status", sa.String(length=64), nullable=False),
        sa.Column("limitation_type", sa.String(length=64), nullable=False),
        sa.Column("condition", sa.Text(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("environment", sa.String(length=255), nullable=True),
        sa.Column("region", sa.String(length=255), nullable=True),
        sa.Column("sku_tier", sa.String(length=255), nullable=True),
        sa.Column("auth_mode", sa.String(length=255), nullable=True),
        sa.Column("network_mode", sa.String(length=255), nullable=True),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("workaround", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=32), nullable=False),
        sa.Column("first_seen", sa.Date(), nullable=True),
        sa.Column("last_seen", sa.Date(), nullable=True),
        sa.Column("verification_state", sa.String(length=32), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("btrim(quote) <> ''", name="ck_limitations_quote_not_blank"),
        sa.CheckConstraint("btrim(confidence) <> ''", name="ck_limitations_confidence_not_blank"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_limitations_service", "limitations", ["service"], unique=False)
    op.create_index(
        "ix_limitations_verification_state",
        "limitations",
        ["verification_state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_limitations_verification_state", table_name="limitations")
    op.drop_index("ix_limitations_service", table_name="limitations")
    op.drop_table("limitations")
    op.drop_table("sources")