from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def main_menu(is_admin: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Регистрация", callback_data="menu:register")],
        [InlineKeyboardButton(text="Мой профиль", callback_data="menu:me")],
        [InlineKeyboardButton(text="Моя статистика", callback_data="menu:mystats")],
        [InlineKeyboardButton(text="Настройки уведомлений", callback_data="menu:notify")],
        [InlineKeyboardButton(text="Цели на войне", callback_data="menu:targets")],
        [InlineKeyboardButton(text="Помощь / Гайд", callback_data="menu:guide")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="Админ-панель", callback_data="menu:admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu_reply(is_admin: bool) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="Регистрация"), KeyboardButton(text="Мой профиль")],
        [KeyboardButton(text="Моя статистика"), KeyboardButton(text="Настройки уведомлений")],
        [KeyboardButton(text="Цели на войне"), KeyboardButton(text="Помощь / Гайд")],
    ]
    if is_admin:
        keyboard.append([KeyboardButton(text="Админ-панель")])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        is_persistent=True,
    )


def registration_reply(is_admin: bool) -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton(text="Отмена")]]
    keyboard.extend(main_menu_reply(is_admin).keyboard)
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        is_persistent=True,
    )


def already_registered_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Показать профиль", callback_data="menu:me")],
            [InlineKeyboardButton(text="Отмена", callback_data="menu:cancel")],
        ]
    )
