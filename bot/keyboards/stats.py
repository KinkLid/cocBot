from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def stats_actions_kb(has_seasons: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="Обновить", callback_data="stats:refresh")]]
    if has_seasons:
        rows.append([InlineKeyboardButton(text="Сезоны", callback_data="stats:seasons")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
