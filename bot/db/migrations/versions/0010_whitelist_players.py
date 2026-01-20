"""add whitelist players table

Revision ID: 0010_whitelist_players
Revises: 0009_clan_member_blacklist_whitelist_tokens
Create Date: 2025-02-11 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_whitelist_players"
down_revision: Union[str, Sequence[str], None] = "0009_clan_member_blacklist_whitelist_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "whitelist_players",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_tag", sa.String(length=16), nullable=False),
        sa.Column("player_name", sa.String(length=64), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("added_by_admin_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("player_tag", name="uq_whitelist_player_tag"),
    )
    op.create_index("idx_whitelist_players_active", "whitelist_players", ["is_active"])


def downgrade() -> None:
    op.drop_index("idx_whitelist_players_active", table_name="whitelist_players")
    op.drop_table("whitelist_players")
