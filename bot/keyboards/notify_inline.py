from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.ui.emoji import DISABLED, ENABLED
from bot.utils.notification_templates import template_options


def _status_emoji(enabled: bool) -> str:
    return ENABLED if enabled else DISABLED


def admin_notify_main_kb(prefs: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{_status_emoji(_category_enabled(prefs, 'war'))} КВ: уведомления",
                    callback_data="an:toggle:war",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{_status_emoji(_category_enabled(prefs, 'cwl'))} ЛВК: уведомления",
                    callback_data="an:toggle:cwl",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{_status_emoji(_category_enabled(prefs, 'capital'))} Рейды: уведомления",
                    callback_data="an:toggle:capital",
                )
            ],
            [
                InlineKeyboardButton(text="⚙️ КВ правила", callback_data="an:rules:war"),
                InlineKeyboardButton(text="⚙️ ЛВК правила", callback_data="an:rules:cwl"),
            ],
            [InlineKeyboardButton(text="⚙️ Рейды правила", callback_data="an:rules:capital")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="an:back")],
        ]
    )


def user_notify_main_kb(dm_enabled: bool, categories: dict[str, bool]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{_status_emoji(dm_enabled)} ЛС уведомления",
                    callback_data="un:toggle:dm",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{_status_emoji(categories.get('war', False))} КВ в ЛС",
                    callback_data="un:toggle:war",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{_status_emoji(categories.get('cwl', False))} ЛВК в ЛС",
                    callback_data="un:toggle:cwl",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{_status_emoji(categories.get('capital', False))} Рейды в ЛС",
                    callback_data="un:toggle:capital",
                )
            ],
            [InlineKeyboardButton(text="⚙️ Мои уведомления", callback_data="un:rules")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="un:back")],
        ]
    )


def notify_rules_action_kb(prefix: str, event_type: str, back_action: str = "menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить уведомление", callback_data=f"{prefix}:add:{event_type}")],
            [InlineKeyboardButton(text="📋 Список уведомлений", callback_data=f"{prefix}:list:{event_type}:1")],
            [InlineKeyboardButton(text="✏️ Изменить уведомление", callback_data=f"{prefix}:pick:{event_type}")],
            [InlineKeyboardButton(text="🗑 Удалить уведомление", callback_data=f"{prefix}:pickdel:{event_type}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"{prefix}:{back_action}")],
        ]
    )


def notify_rules_type_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="КВ", callback_data=f"{prefix}:type:war"),
                InlineKeyboardButton(text="ЛВК", callback_data=f"{prefix}:type:cwl"),
            ],
            [InlineKeyboardButton(text="Рейды", callback_data=f"{prefix}:type:capital")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"{prefix}:menu")],
        ]
    )


def notify_template_kb(prefix: str, event_type: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for template, label in template_options(event_type):
        rows.append([InlineKeyboardButton(text=label, callback_data=f"{prefix}:tmpl:{template}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"{prefix}:action:{event_type}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def notify_delay_kb(prefix: str, event_type: str, delay_seconds: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕1h", callback_data=f"{prefix}:delay:+3600"),
                InlineKeyboardButton(text="➕6h", callback_data=f"{prefix}:delay:+21600"),
                InlineKeyboardButton(text="➕12h", callback_data=f"{prefix}:delay:+43200"),
            ],
            [
                InlineKeyboardButton(text="➕5m", callback_data=f"{prefix}:delay:+300"),
                InlineKeyboardButton(text="➕15m", callback_data=f"{prefix}:delay:+900"),
                InlineKeyboardButton(text="➕30m", callback_data=f"{prefix}:delay:+1800"),
            ],
            [
                InlineKeyboardButton(text="➕10s", callback_data=f"{prefix}:delay:+10"),
                InlineKeyboardButton(text="➕30s", callback_data=f"{prefix}:delay:+30"),
            ],
            [
                InlineKeyboardButton(text="➖1h", callback_data=f"{prefix}:delay:-3600"),
                InlineKeyboardButton(text="➖6h", callback_data=f"{prefix}:delay:-21600"),
                InlineKeyboardButton(text="➖12h", callback_data=f"{prefix}:delay:-43200"),
            ],
            [
                InlineKeyboardButton(text="➖5m", callback_data=f"{prefix}:delay:-300"),
                InlineKeyboardButton(text="➖15m", callback_data=f"{prefix}:delay:-900"),
                InlineKeyboardButton(text="➖30m", callback_data=f"{prefix}:delay:-1800"),
            ],
            [
                InlineKeyboardButton(text="➖10s", callback_data=f"{prefix}:delay:-10"),
                InlineKeyboardButton(text="➖30s", callback_data=f"{prefix}:delay:-30"),
            ],
            [InlineKeyboardButton(text="🔄 Сброс 0", callback_data=f"{prefix}:delay:reset")],
            [
                InlineKeyboardButton(text="✅ Готово", callback_data=f"{prefix}:delay:done"),
                InlineKeyboardButton(text="🔙 Назад", callback_data=f"{prefix}:action:{event_type}"),
            ],
        ]
    )


def notify_save_kb(prefix: str, event_type: str, has_text: bool) -> InlineKeyboardMarkup:
    text_label = "✅ Текст добавлен" if has_text else "📝 Добавить текст"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text_label, callback_data=f"{prefix}:text")],
            [InlineKeyboardButton(text="✅ Сохранить уведомление", callback_data=f"{prefix}:save")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"{prefix}:action:{event_type}")],
        ]
    )


def notify_rule_list_kb(prefix: str, event_type: str, rules: list, page: int, pages: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for rule in rules:
        rows.append(
            [
                InlineKeyboardButton(text="🔁", callback_data=f"{prefix}:toggle:{event_type}:{rule.id}"),
                InlineKeyboardButton(text="✏️", callback_data=f"{prefix}:edit:{event_type}:{rule.id}"),
                InlineKeyboardButton(text="🗑", callback_data=f"{prefix}:delete:{event_type}:{rule.id}"),
            ]
        )
    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}:list:{event_type}:{page - 1}")
        )
    if page < pages:
        nav_row.append(
            InlineKeyboardButton(text="➡️", callback_data=f"{prefix}:list:{event_type}:{page + 1}")
        )
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"{prefix}:action:{event_type}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def notify_rule_edit_kb(prefix: str, event_type: str, rule_id: int, enabled: bool) -> InlineKeyboardMarkup:
    toggle_label = "🔁 Выключить" if enabled else "🔁 Включить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏱ Изменить задержку", callback_data=f"{prefix}:editdelay:{event_type}:{rule_id}")],
            [InlineKeyboardButton(text="📝 Изменить текст", callback_data=f"{prefix}:edittext:{event_type}:{rule_id}")],
            [InlineKeyboardButton(text=toggle_label, callback_data=f"{prefix}:toggle:{event_type}:{rule_id}")],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"{prefix}:delete:{event_type}:{rule_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"{prefix}:list:{event_type}:1")],
        ]
    )


def _category_enabled(prefs: dict, category: str) -> bool:
    values = prefs.get(category, {}) or {}
    return any(values.values())
