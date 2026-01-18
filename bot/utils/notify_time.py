from __future__ import annotations

import re


def parse_delay_to_minutes(text: str) -> int | None:
    cleaned = text.strip().lower()
    match = re.fullmatch(r"(\d+)\s*([hm])?", cleaned)
    if not match:
        return None
    value = int(match.group(1))
    if value <= 0:
        return None
    unit = match.group(2)
    if unit == "m":
        return value
    return value * 60


def format_duration_ru(total_minutes: int) -> str:
    hours = total_minutes // 60
    minutes = total_minutes % 60
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} ч")
    if minutes:
        parts.append(f"{minutes} мин")
    if not parts:
        parts.append("0 мин")
    return " ".join(parts)
