from __future__ import annotations


def build_war_event_key(war_data: dict, clan_tag: str | None) -> str | None:
    war_tag = war_data.get("tag")
    if war_tag:
        return war_tag
    start_time = war_data.get("startTime")
    clan = war_data.get("clan", {}).get("tag") or clan_tag
    if start_time and clan:
        return f"{clan}:{start_time}"
    return clan


def build_cwl_event_key(war_data: dict) -> str | None:
    return war_data.get("tag")


def build_capital_event_key(raid: dict) -> str | None:
    return raid.get("raidSeasonId") or raid.get("startTime") or raid.get("endTime")
