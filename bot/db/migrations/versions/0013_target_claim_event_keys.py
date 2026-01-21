"""add target claim event keys

Revision ID: 0013_target_claim_event_keys
Revises: 0012_target_claim_assignment_fields
Create Date: 2024-01-02 00:00:01.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013_target_claim_event_keys"
down_revision: Union[str, Sequence[str], None] = "0012_target_claim_assignment_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("target_claims", sa.Column("event_type", sa.String(length=16), nullable=True))
    op.add_column("target_claims", sa.Column("event_key", sa.String(length=64), nullable=True))

    op.execute("UPDATE target_claims SET event_type = 'war' WHERE event_type IS NULL")
    op.execute(
        """
        UPDATE target_claims
        SET event_key = COALESCE(wars.war_tag, wars.start_at::text, target_claims.war_id::text)
        FROM wars
        WHERE target_claims.war_id = wars.id
        """
    )
    op.execute("UPDATE target_claims SET event_key = war_id::text WHERE event_key IS NULL")

    op.alter_column("target_claims", "event_type", nullable=False)
    op.alter_column("target_claims", "event_key", nullable=False)

    op.drop_constraint("uq_target_claim", "target_claims", type_="unique")
    op.create_unique_constraint(
        "uq_target_claim",
        "target_claims",
        ["event_type", "event_key", "enemy_position"],
    )
    op.create_index(
        "idx_target_claim_event",
        "target_claims",
        ["event_type", "event_key"],
    )

    op.create_table(
        "war_event_contexts",
        sa.Column("event_type", sa.String(length=16), primary_key=True),
        sa.Column("event_key", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("war_event_contexts")
    op.drop_index("idx_target_claim_event", table_name="target_claims")
    op.drop_constraint("uq_target_claim", "target_claims", type_="unique")
    op.create_unique_constraint(
        "uq_target_claim",
        "target_claims",
        ["war_id", "enemy_position"],
    )
    op.drop_column("target_claims", "event_key")
    op.drop_column("target_claims", "event_type")
