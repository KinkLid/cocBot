from __future__ import annotations

import html
from typing import Any

from bot.utils.war_attacks import collect_missed_attacks

MAX_MESSAGE_LENGTH = 4096


def chunk_message(text: str, max_len: int = MAX_MESSAGE_LENGTH) -> list[str]:
    if len(text) <= max_len:
        return [text]
    lines = text.splitlines()
    if not lines:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1
        if current and current_len + line_len > max_len:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def _resolve_war_sides(war_data: dict[str, Any], clan_tag: str) -> tuple[dict[str, Any], dict[str, Any]]:
    clan = war_data.get("clan", {})
    opponent = war_data.get("opponent", {})
    if clan_tag:
        normalized = clan_tag.upper()
        if opponent.get("tag", "").upper() == normalized and clan.get("tag", "").upper() != normalized:
            return opponent, clan
    return clan, opponent


def _status_emoji(used: int, remaining: int) -> str:
    if used == 0:
        return "🔴"
    if remaining == 1:
        return "🟠"
    return "🟡"


def render_missed_attacks(
    title: str,
    war_data: dict[str, Any],
    clan_tag: str,
    include_overview: bool = True,
) -> str:
    clan, opponent = _resolve_war_sides(war_data, clan_tag)
    missed = collect_missed_attacks({**war_data, "clan": clan})
    lines = [f"<b>{html.escape(title)}</b>"]
    if include_overview:
        clan_stars = clan.get("stars", 0)
        enemy_stars = opponent.get("stars", 0)
        clan_destr = clan.get("destructionPercentage", 0)
        enemy_destr = opponent.get("destructionPercentage", 0)
        lines.append(f"<b>Счёт:</b> ⭐️ {clan_stars} — {enemy_stars} ⭐️")
        lines.append(f"<b>Разрушение:</b> {clan_destr}% — {enemy_destr}%")
    if missed:
        lines.append("<b>Не атаковали:</b>")
        for entry in missed:
            name = html.escape(entry.get("name") or "Игрок")
            th = entry.get("townhall")
            used = int(entry.get("used", 0))
            available = int(entry.get("available", 0))
            remaining = int(entry.get("remaining", 0))
            label = f"{name} (TH{th})" if th else name
            status = _status_emoji(used, remaining)
            lines.append(f"• {status} <b>{label}</b> — <b>{used}/{available}</b>")
        total = len(missed)
        player_word = "игрок" if total == 1 else "игрока" if 1 < total < 5 else "игроков"
        lines.append(f"<b>Итого:</b> {total} {player_word}")
    else:
        lines.append("✅ Все атаки сделаны.")
    return "\n".join(lines)


def render_targets_table(
    rows: list[dict[str, Any]],
    hint: str | None = None,
    max_len: int = MAX_MESSAGE_LENGTH,
) -> list[str]:
    header = "<b>🎯 Цели на войне</b>"
    data_lines: list[str] = []
    free_positions: list[str] = []
    for row in rows:
        pos = row.get("position")
        pos_label = f"#{pos}" if pos else "#?"
        name = html.escape(row.get("name") or "Противник")
        th = row.get("townhall")
        th_label = f"(TH{th})" if th else ""
        base_label = " ".join(part for part in [pos_label, th_label] if part)
        enemy_label = f"{base_label} — <b>{name}</b>"
        if row.get("status") == "taken":
            holder = html.escape(row.get("holder") or "участник")
            data_lines.append(f"• {enemy_label} — ✅ занято: <b>{holder}</b>")
        else:
            data_lines.append(f"• {enemy_label} — ⬜ свободно")
            free_positions.append(pos_label)

    if not data_lines:
        return ["Нет противников для отображения."]

    if free_positions:
        data_lines.append("")
        data_lines.append(f"<b>Свободные:</b> {', '.join(free_positions)}")

    if hint:
        data_lines.append("")
        data_lines.append(f"<i>{html.escape(hint)}</i>")

    chunks: list[str] = []
    for chunk in chunk_message("\n".join([header, *data_lines]), max_len=max_len):
        chunks.append(chunk)
    return chunks


def render_cwl_summary(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "нет данных"
    lines = ["<b>⚔️ Атаки за ЛВК</b>"]
    for entry in rows:
        name = html.escape(entry.get("name", "Игрок"))
        used = entry.get("used", 0)
        available = entry.get("available", 0)
        missed = entry.get("missed", 0)
        suffix = "✅ без пропусков" if missed == 0 else f"⚠️ пропуск {missed}"
        lines.append(f"• <b>{name}</b> — <b>{used}/{available}</b> {suffix}")
    return "\n".join(lines)
