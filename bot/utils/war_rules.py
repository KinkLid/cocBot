from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from bot.utils.coc_time import parse_coc_time


def get_war_start_time(war_data: dict[str, Any] | None) -> datetime | None:
    if not war_data:
        return None
    start_time = parse_coc_time(war_data.get("startTime"))
    if start_time:
        return start_time
    prep_start = parse_coc_time(war_data.get("preparationStartTime"))
    if not prep_start:
        return None
    prep_seconds = war_data.get("preparationTime")
    if prep_seconds is None:
        return prep_start
    try:
        prep_seconds_value = int(prep_seconds)
    except (TypeError, ValueError):
        return prep_start
    return prep_start + timedelta(seconds=prep_seconds_value)


def is_rules_window_active(
    war_start_time: datetime | None,
    now: datetime | None = None,
    hours: int = 12,
) -> bool:
    if not war_start_time:
        return False
    if war_start_time.tzinfo is None:
        war_start_time = war_start_time.replace(tzinfo=timezone.utc)
    if now is None:
        now = datetime.now(timezone.utc)
    return now - war_start_time <= timedelta(hours=hours)
