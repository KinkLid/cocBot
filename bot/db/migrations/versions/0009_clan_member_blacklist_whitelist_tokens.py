"""add clan member state and blacklist/whitelist tokens

Revision ID: 0009_clan_member_blacklist_whitelist_tokens
Revises: 0008_complaints_and_war_attacks
Create Date: 2025-01-12 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_clan_member_blacklist_whitelist_tokens"
down_revision: Union[str, Sequence[str], None] = "0008_complaints_and_war_attacks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("token_hash", sa.String(length=64), nullable=True))

    op.create_table(
        "clan_member_state",
        sa.Column("player_tag", sa.String(length=16), primary_key=True),
        sa.Column("last_seen_name", sa.String(length=64), nullable=False),
        sa.Column("last_seen_in_clan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_rejoined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("leave_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_in_clan", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "blacklist_players",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_tag", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("added_by_admin_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("player_tag", name="uq_blacklist_player_tag"),
    )
    op.create_index("idx_blacklist_players_active", "blacklist_players", ["is_active"])

    op.create_table(
        "whitelist_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_last4", sa.String(length=8), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("added_by_admin_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("token_hash", name="uq_whitelist_token_hash"),
    )
    op.create_index("idx_whitelist_tokens_active", "whitelist_tokens", ["is_active"])


def downgrade() -> None:
    op.drop_index("idx_whitelist_tokens_active", table_name="whitelist_tokens")
    op.drop_table("whitelist_tokens")
    op.drop_index("idx_blacklist_players_active", table_name="blacklist_players")
    op.drop_table("blacklist_players")
    op.drop_table("clan_member_state")
    op.drop_column("users", "token_hash")
