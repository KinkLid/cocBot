from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from bot.ui.labels import (
    admin_notify_rule_label,
    dm_status_label,
    dm_window_label,
    label,
    toggle_label,
)


def main_menu_inline(is_admin: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label("register"), callback_data="menu:register")],
        [InlineKeyboardButton(text=label("profile"), callback_data="menu:me")],
        [InlineKeyboardButton(text=label("stats"), callback_data="menu:mystats")],
        [InlineKeyboardButton(text=label("notifications"), callback_data="menu:notify")],
        [InlineKeyboardButton(text=label("targets"), callback_data="menu:targets")],
        [InlineKeyboardButton(text=label("rules"), callback_data="menu:rules")],
        [InlineKeyboardButton(text=label("complaint"), callback_data="menu:complaint")],
        [InlineKeyboardButton(text=label("guide"), callback_data="menu:guide")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text=label("admin"), callback_data="menu:admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu_reply(is_admin: bool) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=label("register")), KeyboardButton(text=label("profile"))],
        [KeyboardButton(text=label("stats")), KeyboardButton(text=label("notifications"))],
        [KeyboardButton(text=label("targets")), KeyboardButton(text=label("rules"))],
        [KeyboardButton(text=label("complaint")), KeyboardButton(text=label("guide"))],
    ]
    if is_admin:
        keyboard.append([KeyboardButton(text=label("admin"))])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def registration_reply() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=label("show_profile"))],
        [KeyboardButton(text=label("main_menu"))],
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def profile_menu_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=label("main_menu"))]],
        resize_keyboard=True,
    )


def stats_menu_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=label("refresh_stats"))],
            [KeyboardButton(text=label("main_menu"))],
        ],
        resize_keyboard=True,
    )


def notify_menu_reply(dm_enabled: bool, dm_window: str, categories: dict[str, bool]) -> ReplyKeyboardMarkup:
    window_label = dm_window_label(dm_window)
    war_label = toggle_label("notify_war", categories.get("war", False))
    cwl_label = toggle_label("notify_cwl", categories.get("cwl", False))
    capital_label = toggle_label("notify_capital", categories.get("capital", False))
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=dm_status_label(dm_enabled))],
            [KeyboardButton(text=war_label), KeyboardButton(text=cwl_label)],
            [KeyboardButton(text=capital_label)],
            [KeyboardButton(text=window_label)],
            [KeyboardButton(text=label("notify_dm_menu"))],
            [KeyboardButton(text=label("main_menu"))],
        ],
        resize_keyboard=True,
    )


def targets_menu_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=label("targets_select")), KeyboardButton(text=label("targets_table"))],
            [KeyboardButton(text=label("main_menu"))],
        ],
        resize_keyboard=True,
    )


def targets_admin_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=label("targets_select")), KeyboardButton(text=label("targets_table"))],
            [KeyboardButton(text=label("assign_other"))],
            [KeyboardButton(text=label("main_menu"))],
        ],
        resize_keyboard=True,
    )


def admin_menu_reply(missed_label: str | None = None) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=label("admin_clear")), KeyboardButton(text=label("admin_diagnostics"))],
        [KeyboardButton(text=label("admin_users")), KeyboardButton(text=label("admin_complaints"))],
    ]
    if missed_label:
        keyboard.append([KeyboardButton(text=missed_label)])
    keyboard.append([KeyboardButton(text=label("admin_notify_chat"))])
    keyboard.append([KeyboardButton(text=label("admin_notify"))])
    keyboard.append([KeyboardButton(text=label("back"))])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def notify_rules_type_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=label("notify_rules_war")), KeyboardButton(text=label("notify_rules_cwl"))],
            [KeyboardButton(text=label("notify_rules_capital"))],
            [KeyboardButton(text=label("back"))],
        ],
        resize_keyboard=True,
    )


def notify_rules_action_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=label("notify_rules_add"))],
            [KeyboardButton(text=label("notify_rules_active"))],
            [KeyboardButton(text=label("notify_rules_edit"))],
            [KeyboardButton(text=label("notify_rules_delete"))],
            [KeyboardButton(text=label("back"))],
        ],
        resize_keyboard=True,
    )

def admin_notify_menu_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=label("admin_notify_war")), KeyboardButton(text=label("admin_notify_cwl"))],
            [KeyboardButton(text=label("admin_notify_capital"))],
            [KeyboardButton(text=label("back"))],
        ],
        resize_keyboard=True,
    )


def admin_notify_category_reply(category: str, settings: dict[str, bool]) -> ReplyKeyboardMarkup:
    buttons: list[list[KeyboardButton]] = []
    if category == "war":
        buttons = [
            [
                KeyboardButton(text=admin_notify_rule_label("war_preparation", settings.get("preparation", True))),
                KeyboardButton(text=admin_notify_rule_label("war_start", settings.get("start", True))),
            ],
            [
                KeyboardButton(text=admin_notify_rule_label("war_end", settings.get("end", True))),
                KeyboardButton(text=admin_notify_rule_label("war_reminder", settings.get("reminder", True))),
            ],
        ]
    elif category == "cwl":
        buttons = [
            [
                KeyboardButton(text=admin_notify_rule_label("cwl_round_start", settings.get("round_start", True))),
                KeyboardButton(text=admin_notify_rule_label("cwl_round_end", settings.get("round_end", True))),
            ],
            [
                KeyboardButton(text=admin_notify_rule_label("cwl_reminder", settings.get("reminder", True))),
                KeyboardButton(
                    text=admin_notify_rule_label("cwl_monthly_summary", settings.get("monthly_summary", True))
                ),
            ],
        ]
    elif category == "capital":
        buttons = [
            [
                KeyboardButton(text=admin_notify_rule_label("capital_start", settings.get("start", True))),
                KeyboardButton(text=admin_notify_rule_label("capital_end", settings.get("end", True))),
            ],
            [
                KeyboardButton(text=admin_notify_rule_label("capital_reminder", settings.get("reminder", True)))
            ],
        ]
    buttons.append([KeyboardButton(text=label("back"))])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def admin_reminder_type_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=label("admin_reminder_delay")), KeyboardButton(text=label("admin_reminder_time"))],
            [KeyboardButton(text=label("back"))],
        ],
        resize_keyboard=True,
    )


def admin_action_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=label("back"))], [KeyboardButton(text=label("main_menu"))]],
        resize_keyboard=True,
    )
