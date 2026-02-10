from __future__ import annotations

from typing import Any
import html


def collect_missed_attacks(war_data: dict[str, Any]) -> list[dict[str, Any]]:
    clan = war_data.get("clan", {})
    members = clan.get("members", [])
    war_type = str(war_data.get("warType") or "").lower()
    if war_type == "cwl":
        attacks_per_member = 1
    else:
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


def build_missed_attacks_list(missed: list[dict[str, Any]]) -> str:
    if not missed:
        return "нет данных"
    lines = []
    for entry in missed:
        name = html.escape(entry.get("name") or "Игрок")
        th = entry.get("townhall")
        label = f"{name} (TH{th})" if th else name
        attacks = f"{entry.get('used', 0)}/{entry.get('available', 0)}"
        lines.append(f"• {label} — {attacks} атак")
    return "\n".join(lines)


def build_total_attacks_list(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "нет данных"
    lines = []
    for entry in rows:
        name = html.escape(entry.get("name", "Игрок"))
        attacks = f"{entry.get('used', 0)}/{entry.get('available', 0)}"
        missed = entry.get("missed", 0)
        suffix = "✅" if missed == 0 else f"(пропуск {missed})"
        lines.append(f"• {name} — {attacks} атак {suffix}".strip())
    return "\n".join(lines)
