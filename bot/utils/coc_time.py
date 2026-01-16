from __future__ import annotations

from datetime import datetime, timezone


def parse_coc_time(value: str | None) -> datetime | None:
    if not value:
        return None
    formats = ("%Y%m%dT%H%M%S.%fZ", "%Y%m%dT%H%M%SZ")
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
