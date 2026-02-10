"""add relation between war_participation and war_member_stats

Revision ID: 0015_war_participation_member_stats_fk
Revises: 0014_member_stats_and_blacklist_fields
Create Date: 2026-02-10 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "0015_war_participation_member_stats_fk"
down_revision: Union[str, Sequence[str], None] = "0014_member_stats_and_blacklist_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("war_participation")}

    if "member_stats_id" not in columns:
        op.add_column("war_participation", sa.Column("member_stats_id", sa.Integer(), nullable=True))

    fk_names = {
        fk["name"]
        for fk in inspector.get_foreign_keys("war_participation")
        if fk.get("name")
    }
    if "fk_war_participation_member_stats_id" not in fk_names:
        op.create_foreign_key(
            "fk_war_participation_member_stats_id",
            "war_participation",
            "war_member_stats",
            ["member_stats_id"],
            ["id"],
        )


def downgrade() -> None:
    op.drop_constraint("fk_war_participation_member_stats_id", "war_participation", type_="foreignkey")
    op.drop_column("war_participation", "member_stats_id")
