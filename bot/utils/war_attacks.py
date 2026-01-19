from __future__ import annotations

from typing import Any

from bot.utils.tables import build_pre_table


def collect_missed_attacks(war_data: dict[str, Any]) -> list[dict[str, Any]]:
    clan = war_data.get("clan", {})
    members = clan.get("members", [])
    attacks_per_member = war_data.get("attacksPerMember", 2) or 2
    missed: list[dict[str, Any]] = []
    for member in members:
        attacks_raw = member.get("attacks")
        if isinstance(attacks_raw, list):
            used = len(attacks_raw)
        elif isinstance(attacks_raw, int):
            used = attacks_raw
        else:
            used = member.get("attacksUsed", 0) or 0
        remaining = attacks_per_member - used
        if remaining > 0:
            missed.append(
                {
                    "name": member.get("name", "Игрок"),
                    "townhall": member.get("townhallLevel"),
                    "map_position": member.get("mapPosition"),
                    "used": used,
                    "available": attacks_per_member,
                    "remaining": remaining,
                }
            )
    missed.sort(
        key=lambda entry: (
            -(entry.get("townhall") or 0),
            entry.get("map_position") or 0,
        )
    )
    return missed


def build_missed_attacks_table(missed: list[dict[str, Any]]) -> str:
    headers = ["№", "Игрок", "Атак", "Осталось"]
    rows: list[list[str]] = []
    for index, entry in enumerate(missed, start=1):
        name = entry.get("name") or "Игрок"
        th = entry.get("townhall")
        if th:
            name = f"{name} TH{th}"
        attacks = f"{entry.get('used', 0)}/{entry.get('available', 0)}"
        rows.append([str(index), str(name), attacks, str(entry.get("remaining", 0))])
    return build_pre_table(headers, rows, max_widths=[4, 26, 9, 9])


def build_total_attacks_table(rows: list[dict[str, Any]]) -> str:
    headers = ["Игрок", "Атак (сделано/всего)", "Пропуски"]
    table_rows: list[list[str]] = []
    for entry in rows:
        name = entry.get("name", "Игрок")
        attacks = f"{entry.get('used', 0)}/{entry.get('available', 0)}"
        table_rows.append([name, attacks, str(entry.get("missed", 0))])
    return build_pre_table(headers, table_rows, max_widths=[26, 18, 10])
