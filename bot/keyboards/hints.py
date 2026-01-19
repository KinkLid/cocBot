from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def hint_ack_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Понятно", callback_data="hint:ok")]]
    )
