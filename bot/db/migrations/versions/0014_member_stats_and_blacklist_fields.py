"""add member daily stats and war member stats tables

Revision ID: 0014_member_stats_and_blacklist_fields
Revises: 0013_target_claim_event_keys
Create Date: 2024-06-01 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "0014_member_stats_and_blacklist_fields"
down_revision: Union[str, Sequence[str], None] = "0013_target_claim_event_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "member_daily_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_tag", sa.String(length=16), nullable=False),
        sa.Column("player_name", sa.String(length=64), nullable=False),
        sa.Column("donations_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("donations_received_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("capital_contributions_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_member_daily_stats_tag_date",
        "member_daily_stats",
        ["player_tag", "captured_at"],
    )

    op.create_table(
        "war_member_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("war_tag", sa.String(length=32), nullable=False),
        sa.Column("player_tag", sa.String(length=16), nullable=False),
        sa.Column("player_name", sa.String(length=64), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attacks_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attacks_available", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("war_tag", "player_tag", name="uq_war_member_stats"),
    )
    op.create_index("idx_war_member_stats_war", "war_member_stats", ["war_tag"])

    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("blacklist_players")}
    if "left_at" not in columns:
        op.add_column("blacklist_players", sa.Column("left_at", sa.DateTime(timezone=True), nullable=True))
    if "detected_by" not in columns:
        op.add_column("blacklist_players", sa.Column("detected_by", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("blacklist_players", "detected_by")
    op.drop_column("blacklist_players", "left_at")
    op.drop_index("idx_war_member_stats_war", table_name="war_member_stats")
    op.drop_table("war_member_stats")
    op.drop_index("idx_member_daily_stats_tag_date", table_name="member_daily_stats")
    op.drop_table("member_daily_stats")
