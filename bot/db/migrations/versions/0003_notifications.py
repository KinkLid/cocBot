"""add notification settings and reminders

Revision ID: 0003_notifications
Revises: 0002_user_stats_and_claims
Create Date: 2024-01-03 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects import postgresql
import sqlalchemy as sa

revision: str = "0003_notifications"
down_revision: Union[str, Sequence[str], None] = "0002_user_stats_and_claims"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_notify_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("preferences", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id"),
    )
    op.create_table(
        "war_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("war_tag", sa.String(length=32), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("last_notified_state", sa.String(length=16), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("war_tag"),
    )
    op.create_table(
        "war_reminders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("war_id", sa.Integer(), nullable=False),
        sa.Column("fire_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["war_id"], ["wars.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "cwl_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("season", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("notified", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("season"),
    )


def downgrade() -> None:
    op.drop_table("cwl_states")
    op.drop_table("war_reminders")
    op.drop_table("war_states")
    op.drop_table("chat_notify_settings")
