from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.ui.labels import season_label


def seasons_kb(seasons: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = []
    for season_id, name in seasons:
        rows.append([InlineKeyboardButton(text=season_label(name), callback_data=f"season:{season_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
