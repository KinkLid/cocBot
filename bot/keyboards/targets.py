from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def targets_select_kb(enemies: list[dict], taken_positions: set[int]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for enemy in enemies:
        pos = enemy.get("mapPosition")
        if pos in taken_positions:
            continue
        name = enemy.get("name") or "?"
        th = enemy.get("townhallLevel")
        text = f"#{pos} {name} TH{th}" if th else f"#{pos} {name}"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"targets:claim:{pos}")])
    if not rows:
        rows.append([InlineKeyboardButton(text="Нет свободных целей", callback_data="targets:none")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def targets_table_kb(has_claim: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="Обновить таблицу", callback_data="targets:refresh")]]
    if has_claim:
        rows.append([InlineKeyboardButton(text="Снять мою цель", callback_data="targets:unclaim")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
