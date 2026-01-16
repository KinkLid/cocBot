from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def main_menu_inline(is_admin: bool) -> InlineKeyboardMarkup:
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


def registration_reply() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="Показать профиль")],
        [KeyboardButton(text="Главное меню")],
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def profile_menu_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Главное меню")]],
        resize_keyboard=True,
    )


def stats_menu_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Обновить статистику")],
            [KeyboardButton(text="Главное меню")],
        ],
        resize_keyboard=True,
    )


def notify_menu_reply(
    dm_enabled: bool,
    dm_types: dict[str, bool],
    dm_window: str,
) -> ReplyKeyboardMarkup:
    status = "✅ ЛС включены" if dm_enabled else "⛔ ЛС выключены"
    toggle = "Выключить ЛС" if dm_enabled else "Включить ЛС"
    prep_label = "W1 подготовка: ✅" if dm_types.get("preparation", True) else "W1 подготовка: ⛔"
    in_war_label = "W2 война: ✅" if dm_types.get("inWar", True) else "W2 война: ⛔"
    ended_label = "W3 итог: ✅" if dm_types.get("warEnded", True) else "W3 итог: ⛔"
    cwl_label = "W4 ЛВК: ✅" if dm_types.get("cwlEnded", False) else "W4 ЛВК: ⛔"
    window_label = "Время ЛС: всегда" if dm_window == "always" else "Время ЛС: день"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=status)],
            [KeyboardButton(text=toggle)],
            [KeyboardButton(text=prep_label), KeyboardButton(text=in_war_label)],
            [KeyboardButton(text=ended_label), KeyboardButton(text=cwl_label)],
            [KeyboardButton(text=window_label)],
            [KeyboardButton(text="Главное меню")],
        ],
        resize_keyboard=True,
    )


def targets_menu_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Выбрать противника"), KeyboardButton(text="Таблица целей")],
            [KeyboardButton(text="Главное меню")],
        ],
        resize_keyboard=True,
    )


def targets_admin_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Выбрать противника"), KeyboardButton(text="Таблица целей")],
            [KeyboardButton(text="Назначить другому")],
            [KeyboardButton(text="Главное меню")],
        ],
        resize_keyboard=True,
    )


def admin_menu_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Очистить игрока"), KeyboardButton(text="Диагностика")],
            [KeyboardButton(text="Настройки уведомлений чата")],
            [KeyboardButton(text="Создать напоминание о войне")],
            [KeyboardButton(text="Назад")],
        ],
        resize_keyboard=True,
    )


def admin_notify_reply(chat_types: dict[str, bool]) -> ReplyKeyboardMarkup:
    prep_label = (
        "Чат W1 подготовка: ✅" if chat_types.get("preparation", True) else "Чат W1 подготовка: ⛔"
    )
    in_war_label = "Чат W2 война: ✅" if chat_types.get("inWar", True) else "Чат W2 война: ⛔"
    ended_label = "Чат W3 итог: ✅" if chat_types.get("warEnded", True) else "Чат W3 итог: ⛔"
    cwl_label = "Чат W4 ЛВК: ✅" if chat_types.get("cwlEnded", True) else "Чат W4 ЛВК: ⛔"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=prep_label), KeyboardButton(text=in_war_label)],
            [KeyboardButton(text=ended_label), KeyboardButton(text=cwl_label)],
            [KeyboardButton(text="Назад в админку")],
        ],
        resize_keyboard=True,
    )


def admin_reminder_type_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Через N часов"), KeyboardButton(text="Время HH:MM")],
            [KeyboardButton(text="Назад в админку")],
        ],
        resize_keyboard=True,
    )


def admin_action_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Назад")], [KeyboardButton(text="Главное меню")]],
        resize_keyboard=True,
    )
