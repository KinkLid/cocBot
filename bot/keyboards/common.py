from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Регистрация", callback_data="menu:register")],
            [InlineKeyboardButton(text="Мой профиль", callback_data="menu:me")],
            [InlineKeyboardButton(text="Моя статистика", callback_data="menu:mystats")],
            [InlineKeyboardButton(text="Уведомления", callback_data="menu:notify")],
        ]
    )


def main_menu_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/register"), KeyboardButton(text="/me")],
            [KeyboardButton(text="/mystats"), KeyboardButton(text="/notify")],
            [KeyboardButton(text="/targets"), KeyboardButton(text="/whois")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )
