"""create onboarding lifecycle state

Revision ID: 20260806_01
Revises: 20260729_02
Create Date: 2026-08-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_01"
down_revision: str | None = "20260729_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("eula_version", sa.String(length=64), nullable=True))

    op.create_table(
        "lifecycle_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("btrim(event_type) <> ''", name="ck_lifecycle_events_type_not_blank"),
        sa.CheckConstraint(
            "event_type IN ('eula_accepted', 'demo_license_assigned', 'token_created')",
            name="ck_lifecycle_events_type_allowed",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lifecycle_events_user_id", "lifecycle_events", ["user_id"])

    op.create_table(
        "auth_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("credential_hash", sa.String(length=128), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("btrim(purpose) <> ''", name="ck_auth_grants_purpose_not_blank"),
        sa.CheckConstraint(
            "purpose IN ('oauth_state', 'onboarding', 'token_issuance')",
            name="ck_auth_grants_purpose_allowed",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("credential_hash"),
    )
    op.create_index("ix_auth_grants_user_id", "auth_grants", ["user_id"])
    op.create_index("ix_auth_grants_expires_at", "auth_grants", ["expires_at"])

    op.create_index(
        "uq_licenses_active_user",
        "licenses",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    op.drop_index("uq_licenses_active_user", table_name="licenses")
    op.drop_index("ix_auth_grants_expires_at", table_name="auth_grants")
    op.drop_index("ix_auth_grants_user_id", table_name="auth_grants")
    op.drop_table("auth_grants")
    op.drop_index("ix_lifecycle_events_user_id", table_name="lifecycle_events")
    op.drop_table("lifecycle_events")
    op.drop_column("users", "eula_version")