"""add uniqueness and delivery metadata for notification instances

Revision ID: 0011_notification_instances_dedup
Revises: 0010_whitelist_players
Create Date: 2024-05-20 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "0011_notification_instances_dedup"
down_revision: Union[str, Sequence[str], None] = "0010_whitelist_players"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("notification_instances")}
    if "sent_at" not in columns:
        op.add_column("notification_instances", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
    if "last_error" not in columns:
        op.add_column("notification_instances", sa.Column("last_error", sa.Text(), nullable=True))

    constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("notification_instances")}
    if "uq_notification_instance_rule_event" not in constraints:
        op.execute(
            """
            DELETE FROM notification_instances a
            USING notification_instances b
            WHERE a.id > b.id
              AND a.rule_id = b.rule_id
              AND a.event_id = b.event_id
            """
        )
        op.create_unique_constraint(
            "uq_notification_instance_rule_event",
            "notification_instances",
            ["rule_id", "event_id"],
        )


def downgrade() -> None:
    op.drop_constraint(
        "uq_notification_instance_rule_event",
        "notification_instances",
        type_="unique",
    )
    op.drop_column("notification_instances", "last_error")
    op.drop_column("notification_instances", "sent_at")
