from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def targets_kb(enemies: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for enemy in enemies:
        pos = enemy.get("mapPosition")
        name = enemy.get("name") or "?"
        th = enemy.get("townhallLevel")
        text = f"#{pos} {name} TH{th}" if th else f"#{pos} {name}"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"target:{pos}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
