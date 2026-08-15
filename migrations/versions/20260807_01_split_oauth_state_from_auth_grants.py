"""split oauth state from auth grants

Revision ID: 20260807_01
Revises: 20260806_01
Create Date: 2026-08-07 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_01"
down_revision: str | None = "20260806_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("state_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_hash"),
    )
    op.create_index("ix_oauth_states_expires_at", "oauth_states", ["expires_at"])

    op.drop_constraint("ck_auth_grants_purpose_allowed", "auth_grants", type_="check")
    op.create_check_constraint(
        "ck_auth_grants_purpose_allowed",
        "auth_grants",
        "purpose IN ('onboarding', 'token_issuance')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_auth_grants_purpose_allowed", "auth_grants", type_="check")
    op.create_check_constraint(
        "ck_auth_grants_purpose_allowed",
        "auth_grants",
        "purpose IN ('oauth_state', 'onboarding', 'token_issuance')",
    )
    op.drop_index("ix_oauth_states_expires_at", table_name="oauth_states")
    op.drop_table("oauth_states")