from __future__ import annotations

import re

MAX_DELAY_SECONDS = 7 * 24 * 60 * 60


def parse_duration(text: str, max_seconds: int = MAX_DELAY_SECONDS) -> int | None:
    cleaned = text.strip().lower()
    if not cleaned:
        return None
    token_re = re.compile(r"(\d+)\s*([hms])")
    matches = list(token_re.finditer(cleaned))
    if not matches:
        return None
    total_seconds = 0
    pos = 0
    for match in matches:
        if cleaned[pos:match.start()].strip():
            return None
        value = int(match.group(1))
        if value <= 0:
            return None
        unit = match.group(2)
        if unit == "h":
            total_seconds += value * 3600
        elif unit == "m":
            total_seconds += value * 60
        else:
            total_seconds += value
        pos = match.end()
    if cleaned[pos:].strip():
        return None
    if total_seconds <= 0:
        return None
    if max_seconds and total_seconds > max_seconds:
        return None
    return total_seconds


def parse_delay_to_minutes(text: str) -> int | None:
    seconds = parse_duration(text)
    if seconds is None:
        return None
    return max(1, int(round(seconds / 60)))


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


def format_duration_ru_seconds(total_seconds: int) -> str:
    if total_seconds <= 0:
        return "0 сек"
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} ч")
    if minutes:
        parts.append(f"{minutes} мин")
    if seconds:
        parts.append(f"{seconds} сек")
    return " ".join(parts)
