from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.ui.emoji import EMOJI


def targets_select_kb(
    enemies: list[dict],
    taken_positions: set[int],
    my_positions: set[int],
    assign_mode: bool = False,
    admin_rows: list[tuple[str, str]] | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if admin_rows:
        for text, callback in admin_rows:
            rows.append([InlineKeyboardButton(text=text, callback_data=callback)])
    sorted_enemies = sorted(enemies, key=lambda enemy: enemy.get("mapPosition") or 0)
    for enemy in sorted_enemies:
        pos = enemy.get("mapPosition")
        name = enemy.get("name") or "?"
        th = enemy.get("townhallLevel")
        base = f"#{pos} {name} TH{th}" if th else f"#{pos} {name}"
        if pos in my_positions and not assign_mode:
            text = f"{EMOJI['toggle_on']} {base}"
            rows.append([InlineKeyboardButton(text=text, callback_data=f"targets:toggle:{pos}")])
            continue
        if pos in taken_positions:
            continue
        callback = f"targets:assign:{pos}" if assign_mode else f"targets:claim:{pos}"
        rows.append([InlineKeyboardButton(text=f"{EMOJI['targets']} {base}", callback_data=callback)])
    if not rows:
        rows.append([InlineKeyboardButton(text=f"{EMOJI['info']} Нет доступных целей", callback_data="targets:none")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
