"""add complaints and war attack events

Revision ID: 0008_complaints_and_war_attacks
Revises: 0007_user_chat_hints
Create Date: 2024-06-01 00:10:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_complaints_and_war_attacks"
down_revision: Union[str, Sequence[str], None] = "0007_user_chat_hints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "complaints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by_tg_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by_tg_name", sa.String(length=128), nullable=True),
        sa.Column("target_player_tag", sa.String(length=16), nullable=False),
        sa.Column("target_player_name", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
    )
    op.create_index("idx_complaints_status", "complaints", ["status"])

    op.create_table(
        "war_attack_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("war_tag", sa.String(length=32), nullable=False),
        sa.Column("attacker_tag", sa.String(length=16), nullable=False),
        sa.Column("defender_tag", sa.String(length=16), nullable=False),
        sa.Column("attack_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint(
            "war_tag",
            "attacker_tag",
            "defender_tag",
            "attack_order",
            name="uq_war_attack_event",
        ),
    )
    op.create_index("idx_war_attack_event_war", "war_attack_events", ["war_tag"])


def downgrade() -> None:
    op.drop_index("idx_war_attack_event_war", table_name="war_attack_events")
    op.drop_table("war_attack_events")
    op.drop_index("idx_complaints_status", table_name="complaints")
    op.drop_table("complaints")
