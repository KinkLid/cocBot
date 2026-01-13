"""initial

Revision ID: 0001_initial
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("telegram_id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.String(length=64)),
        sa.Column("player_tag", sa.String(length=16), nullable=False),
        sa.Column("player_name", sa.String(length=64), nullable=False),
        sa.Column("clan_tag", sa.String(length=16), nullable=False),
        sa.Column("role_flags", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notify_pref", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint("uq_users_player_tag", "users", ["player_tag"])

    op.create_table(
        "seasons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint("uq_seasons_name", "seasons", ["name"])

    op.create_table(
        "stats_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id")),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )

    op.create_table(
        "wars",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("war_tag", sa.String(length=32)),
        sa.Column("war_type", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True)),
        sa.Column("end_at", sa.DateTime(timezone=True)),
        sa.Column("opponent_name", sa.String(length=64)),
        sa.Column("opponent_tag", sa.String(length=16)),
        sa.Column("league_name", sa.String(length=64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint("uq_wars_war_tag", "wars", ["war_tag"])

    op.create_table(
        "war_participation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("war_id", sa.Integer(), sa.ForeignKey("wars.id")),
        sa.Column("telegram_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id")),
        sa.Column("attacks_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attacks_available", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("destruction", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missed_attacks", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "capital_raid_seasons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("raid_id", sa.String(length=32), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True)),
        sa.Column("end_at", sa.DateTime(timezone=True)),
        sa.Column("total_loot", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint("uq_capital_raid_seasons_raid_id", "capital_raid_seasons", ["raid_id"])

    op.create_table(
        "capital_contrib",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season_id", sa.Integer(), sa.ForeignKey("capital_raid_seasons.id")),
        sa.Column("telegram_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id")),
        sa.Column("attacks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raids_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("capital_gold_donated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("damage", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "target_claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("war_id", sa.Integer(), sa.ForeignKey("wars.id")),
        sa.Column("enemy_position", sa.Integer(), nullable=False),
        sa.Column("claimed_by_telegram_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id")),
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint("uq_target_claim", "target_claims", ["war_id", "enemy_position"])
    op.create_index("idx_target_claim_war", "target_claims", ["war_id"])


def downgrade() -> None:
    op.drop_index("idx_target_claim_war", table_name="target_claims")
    op.drop_constraint("uq_target_claim", "target_claims", type_="unique")
    op.drop_table("target_claims")
    op.drop_table("capital_contrib")
    op.drop_constraint("uq_capital_raid_seasons_raid_id", "capital_raid_seasons", type_="unique")
    op.drop_table("capital_raid_seasons")
    op.drop_table("war_participation")
    op.drop_constraint("uq_wars_war_tag", "wars", type_="unique")
    op.drop_table("wars")
    op.drop_table("stats_daily")
    op.drop_constraint("uq_seasons_name", "seasons", type_="unique")
    op.drop_table("seasons")
    op.drop_constraint("uq_users_player_tag", "users", type_="unique")
    op.drop_table("users")
