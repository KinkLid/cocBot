from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import BotConfig
from bot.db import models
from bot.services.coc_client import CocClient
from bot.utils.coc_time import parse_coc_time
from bot.utils.war_state import find_current_cwl_war


async def schedule_rule_for_active_event(
    session: AsyncSession,
    coc_client: CocClient,
    config: BotConfig,
    rule: models.NotificationRule,
) -> None:
    event_id = None
    start_at: datetime | None = None
    if rule.event_type == "war":
        try:
            war_data = await coc_client.get_current_war(config.clan_tag)
        except Exception:  # noqa: BLE001
            return
        if war_data.get("state") in {"preparation", "inWar"}:
            event_id = war_data.get("tag") or war_data.get("clan", {}).get("tag")
            start_at = parse_coc_time(war_data.get("startTime"))
    elif rule.event_type == "cwl":
        war_data = await find_current_cwl_war(coc_client, config.clan_tag)
        if war_data:
            event_id = war_data.get("tag")
            start_at = parse_coc_time(war_data.get("startTime"))
    elif rule.event_type == "capital":
        try:
            raids = await coc_client.get_capital_raid_seasons(config.clan_tag)
        except Exception:  # noqa: BLE001
            return
        items = raids.get("items", [])
        if items:
            latest = items[0]
            start_at = parse_coc_time(latest.get("startTime"))
            end_at = parse_coc_time(latest.get("endTime"))
            now = datetime.now(timezone.utc)
            if start_at and end_at and start_at <= now <= end_at:
                event_id = latest.get("startTime") or latest.get("endTime") or "raid"
    if not event_id or not start_at:
        return
    existing = (
        await session.execute(
            select(models.NotificationInstance)
            .where(models.NotificationInstance.rule_id == rule.id)
            .where(models.NotificationInstance.event_id == event_id)
        )
    ).scalar_one_or_none()
    if existing:
        return
    session.add(
        models.NotificationInstance(
            rule_id=rule.id,
            event_id=event_id,
            fire_at=start_at + timedelta(seconds=rule.delay_seconds),
            status="pending",
            payload={},
        )
    )
