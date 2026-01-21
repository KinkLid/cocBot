"""add target claim assignment fields

Revision ID: 0012_target_claim_assignment_fields
Revises: 0011_notification_instances_dedup
Create Date: 2024-01-02 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012_target_claim_assignment_fields"
down_revision: Union[str, Sequence[str], None] = "0011_notification_instances_dedup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "target_claims",
        sa.Column("claimed_by_user_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=True),
    )
    op.add_column("target_claims", sa.Column("reserved_for_player_tag", sa.String(length=16), nullable=True))
    op.add_column("target_claims", sa.Column("reserved_for_player_name", sa.String(length=64), nullable=True))
    op.add_column(
        "target_claims",
        sa.Column("reserved_by_admin_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=True),
    )
    op.execute(
        """
        UPDATE target_claims
        SET claimed_by_user_id = claimed_by_telegram_id
        WHERE claimed_by_telegram_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE target_claims
        SET reserved_for_player_name = external_player_name
        WHERE external_player_name IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE target_claims
        SET reserved_for_player_tag = users.player_tag
        FROM users
        WHERE target_claims.claimed_by_telegram_id = users.telegram_id
        AND target_claims.reserved_for_player_tag IS NULL
        """
    )
    op.execute(
        """
        UPDATE target_claims
        SET reserved_for_player_name = users.player_name
        FROM users
        WHERE target_claims.claimed_by_telegram_id = users.telegram_id
        AND target_claims.reserved_for_player_name IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("target_claims", "reserved_by_admin_id")
    op.drop_column("target_claims", "reserved_for_player_name")
    op.drop_column("target_claims", "reserved_for_player_tag")
    op.drop_column("target_claims", "claimed_by_user_id")
