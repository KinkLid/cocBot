"""add clan membership cache fields

Revision ID: 0005_clan_membership_cache
Revises: 0004_notifications_v2
Create Date: 2024-01-20 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_clan_membership_cache"
down_revision: Union[str, Sequence[str], None] = "0004_notifications_v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_clan_check_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("is_in_clan_cached", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "is_in_clan_cached")
    op.drop_column("users", "last_clan_check_at")
