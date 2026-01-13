from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Регистрация", callback_data="menu:register")],
            [InlineKeyboardButton(text="Мой профиль", callback_data="menu:me")],
            [InlineKeyboardButton(text="Моя статистика", callback_data="menu:mystats")],
            [InlineKeyboardButton(text="Уведомления", callback_data="menu:notify")],
        ]
    )
