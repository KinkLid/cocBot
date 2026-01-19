from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.ui.labels import label


def stats_actions_kb(has_seasons: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label("refresh"), callback_data="stats:refresh")]]
    if has_seasons:
        rows.append([InlineKeyboardButton(text=label("seasons"), callback_data="stats:seasons")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
