"""extend notifications for cwl/capital and scheduling

Revision ID: 0004_notifications_v2
Revises: 0003_notifications
Create Date: 2024-01-05 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects import postgresql
import sqlalchemy as sa

revision: str = "0004_notifications_v2"
down_revision: Union[str, Sequence[str], None] = "0003_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cwl_war_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("season", sa.String(length=16), nullable=False),
        sa.Column("war_tag", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("last_notified_state", sa.String(length=16), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("war_tag"),
    )
    op.create_table(
        "capital_raid_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("raid_id", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("last_notified_state", sa.String(length=16), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raid_id"),
    )
    op.create_table(
        "scheduled_notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("fire_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("scheduled_notifications")
    op.drop_table("capital_raid_states")
    op.drop_table("cwl_war_states")
