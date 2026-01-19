from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.ui.labels import label


def notify_channel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label("notify_channel_dm"), callback_data="notify:dm")],
            [InlineKeyboardButton(text=label("notify_channel_chat"), callback_data="notify:chat")],
        ]
    )
