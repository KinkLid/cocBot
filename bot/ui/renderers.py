from __future__ import annotations

import html
from typing import Any

from bot.utils.war_attacks import collect_missed_attacks

MAX_MESSAGE_LENGTH = 4096
DEFAULT_NAME_MAX_LEN = 18


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


def chunk_blocks(blocks: list[str], max_len: int = MAX_MESSAGE_LENGTH) -> list[str]:
    chunks: list[str] = []
    current = ""
    for block in blocks:
        if not block:
            continue
        candidate = block if not current else f"{current}\n\n{block}"
        if current and len(candidate) > max_len:
            chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [""]


def short_name(text: str | None, max_len: int = DEFAULT_NAME_MAX_LEN) -> str:
    if not text:
        return "—"
    value = str(text).strip()
    if not value:
        return "—"
    if len(value) <= max_len:
        return value
    return value[: max_len - 1] + "…"


def format_target_card(
    position: int | None,
    th: int | None,
    status: str,
    owner: str | None,
    enemy_name: str | None = None,
) -> str:
    pos_label = f"#{position}" if position else "#?"
    th_label = f"TH{th}" if th else ""
    header_label = " ".join(part for part in [pos_label, th_label] if part)
    status_label = "занято" if status == "taken" else "свободно"
    status_emoji = "✅" if status == "taken" else "⬜"
    owner_label = html.escape(short_name(owner))
    line_one = f"{status_emoji} <b>{html.escape(header_label)}</b> — {status_label}"
    if enemy_name:
        enemy_label = html.escape(short_name(enemy_name))
        line_one = f"{line_one} • {enemy_label}"
    line_two = f"└ 👤 {owner_label}"
    return f"{line_one}\n{line_two}"


def format_missed_attack_card(
    name: str | None,
    th: int | None,
    attacks_done: int,
    attacks_total: int,
    extra: str | None = None,
) -> str:
    name_label = html.escape(short_name(name))
    th_label = f" (TH{th})" if th else ""
    status_emoji = "✅"
    if attacks_done == 0:
        status_emoji = "🔴"
    elif attacks_done < attacks_total:
        status_emoji = "🟠"
    extra_label = extra
    if not extra_label:
        if attacks_done == 0:
            extra_label = "📝 без атак"
        elif attacks_done < attacks_total:
            extra_label = "⚠️ пропуск атак"
        else:
            extra_label = "—"
    extra_label = html.escape(short_name(extra_label))
    line_one = f"{status_emoji} <b>{name_label}</b>{th_label} — <b>{attacks_done}/{attacks_total}</b>"
    line_two = f"└ {extra_label}"
    return f"{line_one}\n{line_two}"


def render_cards(cards: list[str]) -> str:
    return "\n\n".join(card for card in cards if card) if cards else ""


def _resolve_war_sides(war_data: dict[str, Any], clan_tag: str) -> tuple[dict[str, Any], dict[str, Any]]:
    clan = war_data.get("clan", {})
    opponent = war_data.get("opponent", {})
    if clan_tag:
        normalized = clan_tag.upper()
        if opponent.get("tag", "").upper() == normalized and clan.get("tag", "").upper() != normalized:
            return opponent, clan
    return clan, opponent


def render_missed_attacks(
    title: str,
    war_data: dict[str, Any],
    clan_tag: str,
    include_overview: bool = True,
) -> str:
    clan, opponent = _resolve_war_sides(war_data, clan_tag)
    missed = collect_missed_attacks({**war_data, "clan": clan})
    header_lines = [f"<b>{html.escape(title)}</b>"]
    if include_overview:
        clan_stars = clan.get("stars", 0)
        enemy_stars = opponent.get("stars", 0)
        clan_destr = clan.get("destructionPercentage", 0)
        enemy_destr = opponent.get("destructionPercentage", 0)
        header_lines.append(f"<b>Счёт:</b> ⭐️ {clan_stars} — {enemy_stars} ⭐️")
        header_lines.append(f"<b>Разрушение:</b> {clan_destr}% — {enemy_destr}%")
    blocks: list[str] = ["\n".join(header_lines)]
    if missed:
        blocks.append("<b>Не атаковали:</b>")
        cards: list[str] = []
        for entry in missed:
            name = entry.get("name") or "Игрок"
            th = entry.get("townhall")
            used = int(entry.get("used", 0))
            available = int(entry.get("available", 0))
            cards.append(format_missed_attack_card(name, th, used, available))
        blocks.append(render_cards(cards))
        total = len(missed)
        player_word = "игрок" if total == 1 else "игрока" if 1 < total < 5 else "игроков"
        blocks.append(f"<b>Итого:</b> {total} {player_word}")
    else:
        blocks.append("✅ Все атаки сделаны.")
    return "\n\n".join(blocks)


def render_targets_table(
    rows: list[dict[str, Any]],
    hint: str | None = None,
    max_len: int = MAX_MESSAGE_LENGTH,
) -> list[str]:
    header = "<b>🎯 Цели на войне</b>"
    cards: list[str] = []
    free_positions: list[str] = []
    for row in rows:
        pos = row.get("position")
        pos_label = f"#{pos}" if pos else "#?"
        th = row.get("townhall")
        if row.get("status") == "taken":
            holder = row.get("holder")
            cards.append(format_target_card(pos, th, "taken", holder, row.get("name")))
        else:
            cards.append(format_target_card(pos, th, "free", None, row.get("name")))
            free_positions.append(pos_label)

    if not cards:
        return ["Нет противников для отображения."]

    blocks: list[str] = [header, *cards]

    if free_positions:
        blocks.append(f"<b>Свободные:</b> {', '.join(free_positions)}")

    if hint:
        blocks.append(f"<i>{html.escape(hint)}</i>")

    return chunk_blocks(blocks, max_len=max_len)


def render_cwl_summary(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "нет данных"
    cards: list[str] = []
    for entry in rows:
        name = entry.get("name", "Игрок")
        used = entry.get("used", 0)
        available = entry.get("available", 0)
        missed = entry.get("missed", 0)
        extra = "✅ без пропусков" if missed == 0 else f"⚠️ пропуск {missed}"
        cards.append(format_missed_attack_card(name, None, used, available, extra=extra))
    return "\n\n".join(["<b>⚔️ Атаки за ЛВК</b>", render_cards(cards)])


def render_cwl_problem_summary(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "✅ ЛВК: проблем с атаками не выявлено."
    lines = [
        "⚠️ ЛВК: проблемы с атаками (участвовали >2 войн, атак ≤1, сейчас в клане)",
    ]
    for entry in rows:
        name = html.escape(entry.get("name", "Игрок"))
        wars = entry.get("wars", 0)
        attacks = entry.get("attacks", 0)
        lines.append(f"• {name} (wars: {wars}, attacks: {attacks})")
    return "\n".join(lines)
