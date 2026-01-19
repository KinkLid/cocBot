from __future__ import annotations

from bot.ui.emoji import DISABLED, ENABLED, EMOJI

LABELS = {
    "main_menu": "Главное меню",
    "back": "Назад",
    "register": "Регистрация",
    "profile": "Мой профиль",
    "show_profile": "Показать профиль",
    "mystats": "Моя статистика",
    "refresh_stats": "Обновить статистику",
    "refresh": "Обновить",
    "seasons": "Сезоны",
    "notify": "Уведомления",
    "notify_personal": "Личные уведомления",
    "targets": "Цели на войне",
    "targets_select": "Выбрать противника",
    "targets_table": "Таблица целей",
    "targets_assign": "Назначить другому",
    "rules": "Правила клана",
    "complaint": "Жалоба",
    "complaints": "Жалобы",
    "guide": "Помощь / Гайд",
    "admin": "Админ-панель",
    "admin_clear_player": "Очистить игрока",
    "admin_diagnostics": "Диагностика",
    "admin_users": "Пользователи",
    "admin_blacklist": "Чёрный список",
    "admin_whitelist": "Вайтлист токенов",
    "admin_notify_chat": "Уведомления (чат)",
    "admin_notify": "Уведомления",
    "blacklist_add": "Добавить в ЧС",
    "blacklist_show": "Показать ЧС",
    "blacklist_remove": "Удалить из ЧС",
    "whitelist_add": "Добавить токен",
    "whitelist_show": "Показать вайтлист",
    "whitelist_remove": "Удалить токен",
    "delete": "Удалить",
    "notify_type_war": "КВ",
    "notify_type_cwl": "ЛВК",
    "notify_type_capital": "Рейды",
    "notify_add": "Добавить уведомление",
    "notify_list": "Активные уведомления",
    "notify_edit": "Изменить уведомление",
    "notify_delete": "Удалить / Отключить уведомление",
    "notify_back": "Назад к уведомлениям",
    "notify_channel_dm": "В ЛС",
    "notify_channel_chat": "В общий чат",
    "admin_notify_war": "Клановые войны (чат)",
    "admin_notify_cwl": "ЛВК (чат)",
    "admin_notify_capital": "Рейды столицы (чат)",
    "reminder_delay": "Через задержку",
    "reminder_time": "Время HH:MM",
    "cancel": "Отмена",
    "ack": "Понятно",
    "no_targets": "Нет доступных целей",
}

MENU_ACTIONS = {
    "register": "register",
    "profile": "profile",
    "mystats": "mystats",
    "notify": "notify",
    "targets": "targets",
    "rules": "rules",
    "complaint": "complaint",
    "guide": "guide",
    "admin": "admin",
}


def label(key: str) -> str:
    text = LABELS[key]
    emoji = EMOJI.get(key)
    if emoji:
        return f"{emoji} {text}"
    return text


def label_variants(key: str) -> set[str]:
    base = LABELS[key]
    value = label(key)
    if value == base:
        return {base}
    return {base, value}


def menu_text_actions() -> dict[str, str]:
    actions: dict[str, str] = {}
    for key, action in MENU_ACTIONS.items():
        for variant in label_variants(key):
            actions[variant] = action
    return actions


def is_label(text: str | None, key: str) -> bool:
    if not text:
        return False
    return text in label_variants(key)


def is_main_menu(text: str | None) -> bool:
    return is_label(text, "main_menu")


def is_back(text: str | None) -> bool:
    return is_label(text, "back")


def dm_status_label(enabled: bool) -> str:
    status = "ВКЛ" if enabled else "ВЫКЛ"
    emoji = ENABLED if enabled else DISABLED
    return f"{emoji} ЛС уведомления: {status}"


def category_toggle_label(label_text: str, enabled: bool) -> str:
    status = "ВКЛ" if enabled else "ВЫКЛ"
    emoji = ENABLED if enabled else DISABLED
    return f"{emoji} {label_text} уведомления: {status}"


def dm_window_label(dm_window: str) -> str:
    base = "Режим ЛС: всегда" if dm_window == "always" else "Режим ЛС: только днём"
    return f"🕒 {base}"


def notify_chat_toggle_label(text: str, enabled: bool) -> str:
    emoji = ENABLED if enabled else DISABLED
    return f"{emoji} {text} → чат"


def season_label(name: str) -> str:
    return f"{EMOJI['seasons']} {name}"


def member_label(name: str, tag: str) -> str:
    return f"{EMOJI['profile']} {name} ({tag})"


def admin_unclaim_label(position: int, player_name: str | None = None) -> str:
    base = f"#{position}"
    if player_name:
        base = f"{base} {player_name}"
    return f"{EMOJI['admin_unclaim']} {base}"


def target_label(base: str) -> str:
    return f"{EMOJI['targets']} {base}"


def claimed_target_label(base: str) -> str:
    return f"{ENABLED} {base}"
