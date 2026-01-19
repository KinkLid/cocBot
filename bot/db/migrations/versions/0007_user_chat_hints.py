"""add main chat tracking and user hints

Revision ID: 0007_user_chat_hints
Revises: 0006_notification_rules
Create Date: 2024-06-01 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_user_chat_hints"
down_revision: Union[str, Sequence[str], None] = "0006_notification_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_seen_in_main_chat", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("main_chat_member_check_ok", sa.Boolean(), nullable=True))
    op.add_column("users", sa.Column("seen_hint_targets", sa.Boolean(), nullable=True))
    op.add_column("users", sa.Column("seen_hint_notify", sa.Boolean(), nullable=True))
    op.add_column("users", sa.Column("seen_hint_stats", sa.Boolean(), nullable=True))
    op.add_column("users", sa.Column("seen_hint_admin_notify", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "seen_hint_admin_notify")
    op.drop_column("users", "seen_hint_stats")
    op.drop_column("users", "seen_hint_notify")
    op.drop_column("users", "seen_hint_targets")
    op.drop_column("users", "main_chat_member_check_ok")
    op.drop_column("users", "last_seen_in_main_chat")
