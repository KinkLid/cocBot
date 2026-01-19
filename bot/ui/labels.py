from __future__ import annotations

from bot.ui.emoji import EMOJI

LABELS: dict[str, str] = {
    "main_menu": "Главное меню",
    "register": "Регистрация",
    "profile": "Мой профиль",
    "stats": "Моя статистика",
    "notifications": "Уведомления",
    "targets": "Цели на войне",
    "rules": "Правила клана",
    "complaint": "Жалоба",
    "guide": "Помощь / Гайд",
    "admin": "Админ-панель",
    "show_profile": "Показать профиль",
    "refresh_stats": "Обновить статистику",
    "refresh": "Обновить",
    "seasons": "Сезоны",
    "back": "Назад",
    "back_to_notifications": "Назад к уведомлениям",
    "notify_dm_menu": "Личные уведомления",
    "notify_dm": "Личные уведомления",
    "notify_dm_window_always": "Режим ЛС: всегда",
    "notify_dm_window_day": "Режим ЛС: только днём",
    "notify_war": "КВ уведомления",
    "notify_cwl": "ЛВК уведомления",
    "notify_capital": "Рейды уведомления",
    "notify_rules_war": "КВ",
    "notify_rules_cwl": "ЛВК",
    "notify_rules_capital": "Рейды",
    "notify_rules_add": "Добавить уведомление",
    "notify_rules_active": "Активные уведомления",
    "notify_rules_edit": "Изменить уведомление",
    "notify_rules_delete": "Удалить / Отключить уведомление",
    "notify_channel_dm": "В ЛС",
    "notify_channel_chat": "В общий чат",
    "targets_select": "Выбрать противника",
    "targets_table": "Таблица целей",
    "assign_other": "Назначить другому",
    "admin_clear": "Очистить игрока",
    "admin_diagnostics": "Диагностика",
    "admin_users": "Пользователи",
    "admin_complaints": "Жалобы",
    "admin_notify_chat": "Уведомления (чат)",
    "admin_notify": "Уведомления",
    "admin_notify_war": "Клановые войны (чат)",
    "admin_notify_cwl": "ЛВК (чат)",
    "admin_notify_capital": "Рейды столицы (чат)",
    "admin_reminder_delay": "Через задержку",
    "admin_reminder_time": "Время HH:MM",
    "ack": "Понятно",
    "cancel": "Отмена",
    "delete": "Удалить",
    "missed_attacks_cwl": "Кто не атаковал (ЛВК текущая война)",
    "missed_attacks_war": "Кто не атаковал (КВ сейчас)",
}

ADMIN_NOTIFY_RULES: dict[str, str] = {
    "war_preparation": "КВ: подготовка → чат",
    "war_start": "КВ: старт войны → чат",
    "war_end": "КВ: итоги → чат",
    "war_reminder": "КВ: напоминания → чат",
    "cwl_round_start": "ЛВК: старт раунда → чат",
    "cwl_round_end": "ЛВК: конец раунда → чат",
    "cwl_reminder": "ЛВК: напоминания → чат",
    "cwl_monthly_summary": "Итоги месяца → чат",
    "capital_start": "Столица: старт рейдов → чат",
    "capital_end": "Столица: конец рейдов → чат",
    "capital_reminder": "Столица: напоминания → чат",
}


def label(key: str) -> str:
    text = LABELS[key]
    emoji = EMOJI.get(key)
    return f"{emoji} {text}" if emoji else text


def label_quoted(key: str) -> str:
    return f"«{label(key)}»"


def toggle_label(key: str, enabled: bool) -> str:
    emoji_key = "toggle_on" if enabled else "toggle_off"
    status = "ВКЛ" if enabled else "ВЫКЛ"
    return f"{EMOJI[emoji_key]} {LABELS[key]}: {status}"


def dm_status_label(enabled: bool) -> str:
    emoji_key = "dm_enabled" if enabled else "dm_disabled"
    status = "ВКЛ" if enabled else "ВЫКЛ"
    return f"{EMOJI[emoji_key]} {LABELS['notify_dm']}: {status}"


def dm_window_label(window: str) -> str:
    label_key = "notify_dm_window_always" if window == "always" else "notify_dm_window_day"
    return f"{EMOJI['notify_dm_window']} {LABELS[label_key]}"


def admin_notify_rule_label(rule_key: str, enabled: bool) -> str:
    emoji_key = "toggle_on" if enabled else "toggle_off"
    return f"{EMOJI[emoji_key]} {ADMIN_NOTIFY_RULES[rule_key]}"


def admin_notify_rule_texts() -> set[str]:
    texts = set()
    for rule_key in ADMIN_NOTIFY_RULES:
        texts.add(admin_notify_rule_label(rule_key, True))
        texts.add(admin_notify_rule_label(rule_key, False))
    return texts


def notify_category_toggle_texts() -> set[str]:
    keys = ["notify_war", "notify_cwl", "notify_capital"]
    texts = set()
    for key in keys:
        texts.add(toggle_label(key, True))
        texts.add(toggle_label(key, False))
    return texts


def notify_dm_toggle_texts() -> set[str]:
    return {dm_status_label(True), dm_status_label(False)}


def notify_dm_window_texts() -> set[str]:
    return {dm_window_label("always"), dm_window_label("day")}


def notify_rules_type_texts() -> dict[str, str]:
    return {
        label("notify_rules_war"): "war",
        label("notify_rules_cwl"): "cwl",
        label("notify_rules_capital"): "capital",
    }


def missed_attacks_label(key: str) -> str:
    return f"{EMOJI['missed_attacks']} {LABELS[key]}"
