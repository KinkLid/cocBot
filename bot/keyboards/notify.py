from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def notify_channel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="В ЛС", callback_data="notify:dm")],
            [InlineKeyboardButton(text="В общий чат", callback_data="notify:chat")],
        ]
    )
