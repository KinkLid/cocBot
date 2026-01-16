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


def notify_menu_reply(dm_enabled: bool, dm_window: str) -> ReplyKeyboardMarkup:
    status = "ЛС: ✅ включены" if dm_enabled else "ЛС: ⛔ выключены"
    toggle = "Выключить ЛС" if dm_enabled else "Включить ЛС"
    window_label = "Время ЛС: всегда" if dm_window == "always" else "Время ЛС: день"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=status), KeyboardButton(text=toggle)],
            [KeyboardButton(text="Клановые войны"), KeyboardButton(text="ЛВК")],
            [KeyboardButton(text="Рейды столицы")],
            [KeyboardButton(text=window_label)],
            [KeyboardButton(text="Главное меню")],
        ],
        resize_keyboard=True,
    )


def notify_category_reply(category_label: str, dm_enabled: bool, category_enabled: bool) -> ReplyKeyboardMarkup:
    status = "✅ получать в ЛС" if category_enabled and dm_enabled else "⛔ не получать в ЛС"
    toggle = "Отключить ЛС для раздела" if category_enabled else "Включить ЛС для раздела"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=f"{category_label}: {status}")],
            [KeyboardButton(text=toggle)],
            [KeyboardButton(text="Назад к уведомлениям")],
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
            [KeyboardButton(text="Уведомления")],
            [KeyboardButton(text="Назад")],
        ],
        resize_keyboard=True,
    )

def admin_notify_menu_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Клановые войны (чат)"), KeyboardButton(text="ЛВК (чат)")],
            [KeyboardButton(text="Рейды столицы (чат)")],
            [KeyboardButton(text="Назад")],
        ],
        resize_keyboard=True,
    )


def admin_notify_category_reply(category: str, settings: dict[str, bool]) -> ReplyKeyboardMarkup:
    buttons: list[list[KeyboardButton]] = []
    if category == "war":
        buttons = [
            [
                KeyboardButton(
                    text="КВ: подготовка → чат ✅" if settings.get("preparation", True) else "КВ: подготовка → чат ⛔"
                ),
                KeyboardButton(
                    text="КВ: старт войны → чат ✅" if settings.get("start", True) else "КВ: старт войны → чат ⛔"
                ),
            ],
            [
                KeyboardButton(
                    text="КВ: итоги → чат ✅" if settings.get("end", True) else "КВ: итоги → чат ⛔"
                ),
                KeyboardButton(
                    text="КВ: напоминания → чат ✅" if settings.get("reminder", True) else "КВ: напоминания → чат ⛔"
                ),
            ],
            [KeyboardButton(text="Создать напоминание КВ")],
        ]
    elif category == "cwl":
        buttons = [
            [
                KeyboardButton(
                    text="ЛВК: старт раунда → чат ✅"
                    if settings.get("round_start", True)
                    else "ЛВК: старт раунда → чат ⛔"
                ),
                KeyboardButton(
                    text="ЛВК: конец раунда → чат ✅"
                    if settings.get("round_end", True)
                    else "ЛВК: конец раунда → чат ⛔"
                ),
            ],
            [
                KeyboardButton(
                    text="ЛВК: напоминания → чат ✅"
                    if settings.get("reminder", True)
                    else "ЛВК: напоминания → чат ⛔"
                ),
                KeyboardButton(
                    text="Итоги месяца → чат ✅"
                    if settings.get("monthly_summary", True)
                    else "Итоги месяца → чат ⛔"
                ),
            ],
            [KeyboardButton(text="Создать напоминание ЛВК")],
        ]
    elif category == "capital":
        buttons = [
            [
                KeyboardButton(
                    text="Столица: старт рейдов → чат ✅"
                    if settings.get("start", True)
                    else "Столица: старт рейдов → чат ⛔"
                ),
                KeyboardButton(
                    text="Столица: конец рейдов → чат ✅"
                    if settings.get("end", True)
                    else "Столица: конец рейдов → чат ⛔"
                ),
            ],
            [
                KeyboardButton(
                    text="Столица: напоминания → чат ✅"
                    if settings.get("reminder", True)
                    else "Столица: напоминания → чат ⛔"
                )
            ],
            [KeyboardButton(text="Создать напоминание столицы")],
        ]
    buttons.append([KeyboardButton(text="Назад")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def admin_reminder_type_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Через N часов"), KeyboardButton(text="Время HH:MM")],
            [KeyboardButton(text="Назад")],
        ],
        resize_keyboard=True,
    )


def admin_action_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Назад")], [KeyboardButton(text="Главное меню")]],
        resize_keyboard=True,
    )
