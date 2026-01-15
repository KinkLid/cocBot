"""add stats message id and external claims

Revision ID: 0002_user_stats_and_claims
Revises: 0001_initial
Create Date: 2024-01-02 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_user_stats_and_claims"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_stats_message_id", sa.Integer(), nullable=True))
    op.add_column("target_claims", sa.Column("external_player_name", sa.String(length=64), nullable=True))
    op.alter_column("target_claims", "claimed_by_telegram_id", existing_type=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    op.alter_column("target_claims", "claimed_by_telegram_id", existing_type=sa.BigInteger(), nullable=False)
    op.drop_column("target_claims", "external_player_name")
    op.drop_column("users", "last_stats_message_id")
