from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import (
    admin_action_reply,
    admin_menu_reply,
    admin_notify_category_reply,
    admin_notify_menu_reply,
    main_menu_reply,
    notify_rules_action_reply,
    notify_rules_type_reply,
)
from bot.services.coc_client import CocClient
from bot.services.notifications import NotificationService, normalize_chat_prefs
from bot.services.permissions import is_admin
from bot.utils.coc_time import parse_coc_time
from bot.utils.navigation import pop_menu, reset_menu, set_menu
from bot.utils.notify_time import format_duration_ru, parse_delay_to_minutes
from bot.utils.state import reset_state_if_any
from bot.utils.tables import build_pre_table
from bot.utils.war_attacks import build_missed_attacks_table, collect_missed_attacks
from bot.utils.war_state import find_current_cwl_war, get_missed_attacks_label
from bot.utils.notification_rules import schedule_rule_for_active_event

logger = logging.getLogger(__name__)
router = Router()

USERS_PAGE_SIZE = 10
ADMIN_EVENT_LABELS = {
    "war": "КВ",
    "cwl": "ЛВК",
    "capital": "Рейды",
}


class AdminState(StatesGroup):
    waiting_wipe_target = State()
    rule_choose_type = State()
    rule_action = State()
    rule_delay_value = State()
    rule_text = State()
    rule_edit_id = State()
    rule_edit_delay = State()
    rule_edit_text = State()
    rule_toggle_delete = State()


async def _get_chat_prefs(
    sessionmaker: async_sessionmaker,
    config: BotConfig,
) -> dict:
    async with sessionmaker() as session:
        settings = (
            await session.execute(
                select(models.ChatNotificationSetting).where(
                    models.ChatNotificationSetting.chat_id == config.main_chat_id
                )
            )
        ).scalar_one_or_none()
        if not settings:
            settings = models.ChatNotificationSetting(
                chat_id=config.main_chat_id, preferences={}
            )
            session.add(settings)
            await session.flush()
        prefs = normalize_chat_prefs(settings.preferences)
        settings.preferences = prefs
        await session.commit()
        return prefs


async def _update_chat_pref(
    sessionmaker: async_sessionmaker,
    config: BotConfig,
    category: str,
    key: str,
) -> dict:
    async with sessionmaker() as session:
        settings = (
            await session.execute(
                select(models.ChatNotificationSetting).where(
                    models.ChatNotificationSetting.chat_id == config.main_chat_id
                )
            )
        ).scalar_one_or_none()
        if not settings:
            settings = models.ChatNotificationSetting(
                chat_id=config.main_chat_id, preferences={}
            )
            session.add(settings)
            await session.flush()
        prefs = normalize_chat_prefs(settings.preferences)
        prefs[category][key] = not prefs[category].get(key, False)
        settings.preferences = prefs
        await session.commit()
        return prefs


def _format_datetime(value: datetime | None, zone: ZoneInfo) -> str:
    if not value:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(zone).strftime("%Y-%m-%d %H:%M")


def _rules_table(rows: list[models.NotificationRule]) -> str:
    table_rows: list[list[str]] = []
    for rule in rows:
        status = "ВКЛ" if rule.is_enabled else "ВЫКЛ"
        delay_text = format_duration_ru(rule.delay_seconds // 60)
        custom = rule.custom_text or "—"
        table_rows.append([str(rule.id), delay_text, status, custom])
    return build_pre_table(
        ["ID", "Задержка", "Статус", "Текст"],
        table_rows,
        max_widths=[5, 10, 6, 24],
    )


def _users_table(
    users: list[models.User],
    clan_joined: dict[str, datetime | None],
    zone: ZoneInfo,
) -> str:
    rows: list[list[str]] = []
    for user in users:
        tg_name = f"@{user.username}" if user.username else "без username"
        created_at = _format_datetime(user.created_at, zone)
        joined_at = clan_joined.get(user.player_tag.upper())
        if joined_at:
            joined_text = _format_datetime(joined_at, zone)
        elif user.first_seen_in_clan_at:
            joined_text = f"замечен с {_format_datetime(user.first_seen_in_clan_at, zone)}"
        else:
            joined_text = "—"
        rows.append(
            [
                user.player_name,
                tg_name,
                str(user.telegram_id),
                created_at,
                joined_text,
            ]
        )
    return build_pre_table(
        ["CoC", "Telegram", "ID", "Регистрация", "Клан"],
        rows,
        max_widths=[16, 16, 12, 16, 20],
    )


def _users_pagination_kb(page: int, total_pages: int) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"admin_users:page:{page - 1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"admin_users:page:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="admin_users:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _handle_admin_escape(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> bool:
    if message.text == "Главное меню":
        await reset_state_if_any(state)
        await reset_menu(state)
        await message.answer(
            "Главное меню.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return True
    if message.text == "Назад":
        await reset_state_if_any(state)
        await _show_admin_menu_for_stack(message, state, config, sessionmaker, coc_client)
        return True
    return False


async def _show_admin_menu_for_stack(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    data = await state.get_data()
    stack = list(data.get("menu_stack", []))
    current = stack[-1] if stack else None
    if current == "admin_menu":
        missed_label = await get_missed_attacks_label(coc_client, config.clan_tag)
        await message.answer("Админ-панель.", reply_markup=admin_menu_reply(missed_label))
        return
    if current == "admin_notify_menu":
        await message.answer("Уведомления: общий чат.", reply_markup=admin_notify_menu_reply())
        return
    if current in {"admin_notify_war", "admin_notify_cwl", "admin_notify_capital"}:
        prefs = await _get_chat_prefs(sessionmaker, config)
        category_map = {
            "admin_notify_war": "war",
            "admin_notify_cwl": "cwl",
            "admin_notify_capital": "capital",
        }
        category = category_map[current]
        await message.answer(
            "Настройки уведомлений.",
            reply_markup=admin_notify_category_reply(category, prefs.get(category, {})),
        )
        return
    await reset_menu(state)
    await message.answer(
        "Главное меню.",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )

@router.message(Command("notifytest"))
async def admin_notify_test(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Укажите тип уведомления: war_preparation, war_start, war_end, cwl_round_start, cwl_round_end, "
            "capital_start, capital_end.",
            reply_markup=admin_menu_reply(),
        )
        return
    notify_type = args[1].strip()
    notifier = NotificationService(message.bot, config, sessionmaker, coc_client)
    await notifier.send_test_notification(notify_type)
    await message.answer("Тестовое уведомление отправлено.", reply_markup=admin_menu_reply())

@router.message(Command("wipe"))
async def wipe_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await state.set_state(AdminState.waiting_wipe_target)
    await message.answer(
        "Пришлите тег игрока или ответьте на сообщение пользователя.",
        reply_markup=admin_action_reply(),
    )


@router.message(F.text == "Админ-панель")
async def admin_panel_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await reset_menu(state)
    await set_menu(state, "admin_menu")
    missed_label = await get_missed_attacks_label(coc_client, config.clan_tag)
    await message.answer("Админ-панель.", reply_markup=admin_menu_reply(missed_label))


@router.message(F.text == "Очистить игрока")
async def wipe_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await state.set_state(AdminState.waiting_wipe_target)
    await message.answer(
        "Пришлите тег игрока или ответьте на сообщение пользователя.",
        reply_markup=admin_action_reply(),
    )


@router.message(F.text == "Диагностика")
async def diagnostics_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    async with sessionmaker() as session:
        users_count = (await session.execute(select(models.User))).scalars().all()
        wars_count = (await session.execute(select(models.War))).scalars().all()
    await message.answer(
        f"Диагностика: пользователей {len(users_count)}, войн {len(wars_count)}.",
        reply_markup=admin_menu_reply(),
    )


async def _send_users_page(
    message: Message,
    page: int,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    page = max(1, page)
    async with sessionmaker() as session:
        total = (await session.execute(select(models.User))).scalars().all()
        total_count = len(total)
        users = (
            await session.execute(
                select(models.User)
                .order_by(models.User.created_at.desc())
                .limit(USERS_PAGE_SIZE)
                .offset((page - 1) * USERS_PAGE_SIZE)
            )
        ).scalars().all()
    total_pages = max(1, (total_count + USERS_PAGE_SIZE - 1) // USERS_PAGE_SIZE)
    try:
        clan_members = await coc_client.get_clan_members(config.clan_tag)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load clan members: %s", exc)
        clan_members = {}
    clan_joined: dict[str, datetime | None] = {}
    for member in clan_members.get("items", []):
        tag = (member.get("tag") or "").upper()
        joined_at = parse_coc_time(member.get("joinedAt"))
        clan_joined[tag] = joined_at
    zone = ZoneInfo(config.timezone)
    table = _users_table(users, clan_joined, zone)
    await message.answer(
        f"Пользователи (страница {page}/{total_pages}).\n{table}",
        reply_markup=_users_pagination_kb(page, total_pages),
        parse_mode=ParseMode.HTML,
    )


@router.message(F.text == "👥 Пользователи")
async def admin_users_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await _send_users_page(message, 1, config, sessionmaker, coc_client)


@router.callback_query(lambda c: c.data and c.data.startswith("admin_users:"))
async def admin_users_page(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    await callback.answer("Обновляю…")
    await reset_state_if_any(state)
    if not is_admin(callback.from_user.id, config):
        await callback.message.answer("Админ-панель доступна только администраторам.")
        return
    payload = callback.data.split(":")[1:]
    action = payload[0] if payload else ""
    if action == "back":
        missed_label = await get_missed_attacks_label(coc_client, config.clan_tag)
        await callback.message.answer("Админ-панель.", reply_markup=admin_menu_reply(missed_label))
        return
    if action == "page" and len(payload) > 1 and payload[1].isdigit():
        page = int(payload[1])
        await _send_users_page(callback.message, page, config, sessionmaker, coc_client)
        return


@router.message(F.text.startswith("📋 Кто не атаковал"))
async def admin_missed_attacks_now(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    cwl_war = await find_current_cwl_war(coc_client, config.clan_tag)
    if cwl_war:
        missed = collect_missed_attacks(cwl_war)
        if not missed:
            await message.answer("Все атаки сделаны.", reply_markup=admin_menu_reply())
            return
        table = build_missed_attacks_table(missed)
        await message.answer(
            f"ЛВК текущая война: кто не атаковал.\n{table}",
            reply_markup=admin_menu_reply(),
            parse_mode=ParseMode.HTML,
        )
        return
    try:
        war = await coc_client.get_current_war(config.clan_tag)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load current war: %s", exc)
        await message.answer("Не удалось получить данные о войне.", reply_markup=admin_menu_reply())
        return
    if war.get("state") not in {"preparation", "inWar"}:
        await message.answer("Сейчас нет активной войны.", reply_markup=admin_menu_reply())
        return
    missed = collect_missed_attacks(war)
    if not missed:
        await message.answer("Все атаки сделаны.", reply_markup=admin_menu_reply())
        return
    table = build_missed_attacks_table(missed)
    await message.answer(
        f"КВ сейчас: кто не атаковал.\n{table}",
        reply_markup=admin_menu_reply(),
        parse_mode=ParseMode.HTML,
    )


@router.message(F.text == "Назад")
async def admin_back(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    await reset_state_if_any(state)
    logger.info("Admin back pressed by user_id=%s", message.from_user.id)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Главное меню.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    previous = await pop_menu(state)
    if previous == "admin_menu":
        missed_label = await get_missed_attacks_label(coc_client, config.clan_tag)
        await message.answer("Админ-панель.", reply_markup=admin_menu_reply(missed_label))
        return
    if previous == "admin_notify_menu":
        await message.answer("Уведомления: общий чат.", reply_markup=admin_notify_menu_reply())
        return
    if previous in {"admin_notify_war", "admin_notify_cwl", "admin_notify_capital"}:
        category_map = {
            "admin_notify_war": "war",
            "admin_notify_cwl": "cwl",
            "admin_notify_capital": "capital",
        }
        prefs = await _get_chat_prefs(sessionmaker, config)
        category = category_map[previous]
        await message.answer(
            "Настройки уведомлений.",
            reply_markup=admin_notify_category_reply(category, prefs.get(category, {})),
        )
        return
    await reset_menu(state)
    await message.answer(
        "Главное меню.",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )


@router.message(F.text == "Уведомления")
async def admin_notify_menu(
    message: Message,
    state: FSMContext,
    config: BotConfig,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await set_menu(state, "admin_notify_menu")
    await message.answer("Уведомления: общий чат.", reply_markup=admin_notify_menu_reply())


@router.message(F.text.in_({"Клановые войны (чат)", "ЛВК (чат)", "Рейды столицы (чат)"}))
async def admin_notify_category(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    category_map = {
        "Клановые войны (чат)": ("war", "admin_notify_war"),
        "ЛВК (чат)": ("cwl", "admin_notify_cwl"),
        "Рейды столицы (чат)": ("capital", "admin_notify_capital"),
    }
    category, menu_key = category_map.get(message.text, (None, None))
    if not category:
        return
    prefs = await _get_chat_prefs(sessionmaker, config)
    await set_menu(state, menu_key)
    await message.answer(
        "Настройки уведомлений.",
        reply_markup=admin_notify_category_reply(category, prefs.get(category, {})),
    )


@router.message(
    F.text.startswith("КВ:")
    | F.text.startswith("ЛВК:")
    | F.text.startswith("Столица:")
    | F.text.startswith("Итоги месяца")
)
async def admin_notify_toggle(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    text = message.text or ""
    mapping = {
        "КВ: подготовка": ("war", "preparation"),
        "КВ: старт войны": ("war", "start"),
        "КВ: итоги": ("war", "end"),
        "КВ: напоминания": ("war", "reminder"),
        "ЛВК: старт раунда": ("cwl", "round_start"),
        "ЛВК: конец раунда": ("cwl", "round_end"),
        "ЛВК: напоминания": ("cwl", "reminder"),
        "Итоги месяца": ("cwl", "monthly_summary"),
        "Столица: старт рейдов": ("capital", "start"),
        "Столица: конец рейдов": ("capital", "end"),
        "Столица: напоминания": ("capital", "reminder"),
    }
    key = None
    category = None
    for prefix, (cat, name) in mapping.items():
        if text.startswith(prefix):
            category = cat
            key = name
            break
    if not category or not key:
        await message.answer("Не удалось определить тип.")
        return
    prefs = await _update_chat_pref(sessionmaker, config, category, key)
    await message.answer(
        "Настройки обновлены.",
        reply_markup=admin_notify_category_reply(category, prefs.get(category, {})),
    )


@router.message(F.text == "🔔 Уведомления (чат)")
async def admin_rules_menu(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await state.set_state(AdminState.rule_choose_type)
    await message.answer("Выберите тип уведомлений.", reply_markup=notify_rules_type_reply())


@router.message(AdminState.rule_choose_type)
async def admin_rules_choose_type(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if await _handle_admin_escape(message, state, config, sessionmaker, coc_client):
        return
    if message.text == "Назад":
        missed_label = await get_missed_attacks_label(coc_client, config.clan_tag)
        await message.answer("Админ-панель.", reply_markup=admin_menu_reply(missed_label))
        await state.clear()
        return
    event_type = {"КВ": "war", "ЛВК": "cwl", "Рейды": "capital"}.get(message.text)
    if not event_type:
        await message.answer("Нужно выбрать вариант.", reply_markup=notify_rules_type_reply())
        return
    await state.update_data(rule_event_type=event_type)
    await state.set_state(AdminState.rule_action)
    await message.answer(
        f"Управление уведомлениями: {ADMIN_EVENT_LABELS[event_type]}.",
        reply_markup=notify_rules_action_reply(),
    )


@router.message(AdminState.rule_action)
async def admin_rules_action(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if await _handle_admin_escape(message, state, config, sessionmaker, coc_client):
        return
    if message.text == "Назад":
        await state.set_state(AdminState.rule_choose_type)
        await message.answer("Выберите тип уведомлений.", reply_markup=notify_rules_type_reply())
        return
    data = await state.get_data()
    event_type = data.get("rule_event_type")
    if event_type not in {"war", "cwl", "capital"}:
        await state.clear()
        missed_label = await get_missed_attacks_label(coc_client, config.clan_tag)
        await message.answer("Админ-панель.", reply_markup=admin_menu_reply(missed_label))
        return
    if message.text == "➕ Добавить уведомление":
        await state.set_state(AdminState.rule_delay_value)
        await message.answer(
            "Введите задержку от старта события (например, 1h, 30m, 0.1h).",
            reply_markup=notify_rules_action_reply(),
        )
        return
    if message.text == "📋 Активные уведомления":
        async with sessionmaker() as session:
            rules = (
                await session.execute(
                    select(models.NotificationRule)
                    .where(models.NotificationRule.chat_id == config.main_chat_id)
                    .where(models.NotificationRule.event_type == event_type)
                    .order_by(models.NotificationRule.created_at.desc())
                )
            ).scalars().all()
        if not rules:
            await message.answer("Активных уведомлений нет.", reply_markup=notify_rules_action_reply())
            return
        await message.answer(
            f"Уведомления: {ADMIN_EVENT_LABELS[event_type]}.\n{_rules_table(rules)}",
            reply_markup=notify_rules_action_reply(),
            parse_mode=ParseMode.HTML,
        )
        return
    if message.text == "✏️ Изменить уведомление":
        await state.set_state(AdminState.rule_edit_id)
        await message.answer("Введите ID уведомления для изменения.", reply_markup=notify_rules_action_reply())
        return
    if message.text == "🗑 Удалить / Отключить уведомление":
        await state.set_state(AdminState.rule_toggle_delete)
        await message.answer(
            "Введите ID и действие: включить, отключить или удалить. Пример: 12 отключить.",
            reply_markup=notify_rules_action_reply(),
        )
        return
    await message.answer("Нужно выбрать действие.", reply_markup=notify_rules_action_reply())


@router.message(AdminState.rule_delay_value)
async def admin_rule_delay_value(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if await _handle_admin_escape(message, state, config, sessionmaker, coc_client):
        return
    if message.text == "Назад":
        await state.set_state(AdminState.rule_action)
        await message.answer("Выберите действие.", reply_markup=notify_rules_action_reply())
        return
    delay_minutes = parse_delay_to_minutes(message.text or "")
    if not delay_minutes:
        await message.answer("Нужен формат 1h, 30m или 0.1h.", reply_markup=notify_rules_action_reply())
        return
    await state.update_data(rule_delay_minutes=delay_minutes)
    await state.set_state(AdminState.rule_text)
    await message.answer("Введите текст уведомления или '-' без текста.", reply_markup=notify_rules_action_reply())


@router.message(AdminState.rule_text)
async def admin_rule_text(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if await _handle_admin_escape(message, state, config, sessionmaker, coc_client):
        return
    if message.text == "Назад":
        await state.set_state(AdminState.rule_action)
        await message.answer("Выберите действие.", reply_markup=notify_rules_action_reply())
        return
    data = await state.get_data()
    event_type = data.get("rule_event_type")
    delay_minutes = data.get("rule_delay_minutes")
    if event_type not in {"war", "cwl", "capital"} or not delay_minutes:
        await state.clear()
        missed_label = await get_missed_attacks_label(coc_client, config.clan_tag)
        await message.answer("Админ-панель.", reply_markup=admin_menu_reply(missed_label))
        return
    text = (message.text or "").strip()
    custom_text = "" if text == "-" else text
    async with sessionmaker() as session:
        rule = models.NotificationRule(
            scope="chat",
            chat_id=config.main_chat_id,
            event_type=event_type,
            delay_seconds=int(delay_minutes * 60),
            custom_text=custom_text,
            is_enabled=True,
        )
        session.add(rule)
        await session.flush()
        await schedule_rule_for_active_event(session, coc_client, config, rule)
        await session.commit()
    await state.set_state(AdminState.rule_action)
    await message.answer(
        f"Уведомление добавлено: через {format_duration_ru(delay_minutes)}.",
        reply_markup=notify_rules_action_reply(),
    )


@router.message(AdminState.rule_edit_id)
async def admin_rule_edit_id(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if await _handle_admin_escape(message, state, config, sessionmaker, coc_client):
        return
    if message.text == "Назад":
        await state.set_state(AdminState.rule_action)
        await message.answer("Выберите действие.", reply_markup=notify_rules_action_reply())
        return
    if not (message.text or "").isdigit():
        await message.answer("Нужен числовой ID.", reply_markup=notify_rules_action_reply())
        return
    await state.update_data(rule_edit_id=int(message.text))
    await state.set_state(AdminState.rule_edit_delay)
    await message.answer(
        "Введите новую задержку (1h, 30m) или '-' чтобы оставить.",
        reply_markup=notify_rules_action_reply(),
    )


@router.message(AdminState.rule_edit_delay)
async def admin_rule_edit_delay(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if await _handle_admin_escape(message, state, config, sessionmaker, coc_client):
        return
    if message.text == "Назад":
        await state.set_state(AdminState.rule_action)
        await message.answer("Выберите действие.", reply_markup=notify_rules_action_reply())
        return
    text = (message.text or "").strip()
    delay_minutes = None
    if text != "-":
        delay_minutes = parse_delay_to_minutes(text)
        if not delay_minutes:
            await message.answer("Нужен формат 1h, 30m или '-'.", reply_markup=notify_rules_action_reply())
            return
    await state.update_data(rule_edit_delay=delay_minutes)
    await state.set_state(AdminState.rule_edit_text)
    await message.answer("Введите новый текст или '-' чтобы оставить.", reply_markup=notify_rules_action_reply())


@router.message(AdminState.rule_edit_text)
async def admin_rule_edit_text(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if await _handle_admin_escape(message, state, config, sessionmaker, coc_client):
        return
    if message.text == "Назад":
        await state.set_state(AdminState.rule_action)
        await message.answer("Выберите действие.", reply_markup=notify_rules_action_reply())
        return
    data = await state.get_data()
    event_type = data.get("rule_event_type")
    rule_id = data.get("rule_edit_id")
    if event_type not in {"war", "cwl", "capital"} or not rule_id:
        await state.clear()
        missed_label = await get_missed_attacks_label(coc_client, config.clan_tag)
        await message.answer("Админ-панель.", reply_markup=admin_menu_reply(missed_label))
        return
    new_delay = data.get("rule_edit_delay")
    text_input = (message.text or "").strip()
    custom_text = None if text_input == "-" else text_input
    async with sessionmaker() as session:
        rule = (
            await session.execute(
                select(models.NotificationRule)
                .where(models.NotificationRule.id == rule_id)
                .where(models.NotificationRule.chat_id == config.main_chat_id)
                .where(models.NotificationRule.event_type == event_type)
            )
        ).scalar_one_or_none()
        if not rule:
            await message.answer("Уведомление не найдено.", reply_markup=notify_rules_action_reply())
            await state.set_state(AdminState.rule_action)
            return
        if new_delay is not None:
            rule.delay_seconds = int(new_delay * 60)
        if custom_text is not None:
            rule.custom_text = custom_text
        await session.commit()
    await state.set_state(AdminState.rule_action)
    await message.answer("Уведомление обновлено.", reply_markup=notify_rules_action_reply())


@router.message(AdminState.rule_toggle_delete)
async def admin_rule_toggle_delete(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if await _handle_admin_escape(message, state, config, sessionmaker, coc_client):
        return
    if message.text == "Назад":
        await state.set_state(AdminState.rule_action)
        await message.answer("Выберите действие.", reply_markup=notify_rules_action_reply())
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[0].isdigit():
        await message.answer(
            "Нужен формат: ID действие (включить/отключить/удалить).",
            reply_markup=notify_rules_action_reply(),
        )
        return
    rule_id = int(parts[0])
    action = parts[1].lower()
    data = await state.get_data()
    event_type = data.get("rule_event_type")
    if event_type not in {"war", "cwl", "capital"}:
        await state.clear()
        missed_label = await get_missed_attacks_label(coc_client, config.clan_tag)
        await message.answer("Админ-панель.", reply_markup=admin_menu_reply(missed_label))
        return
    async with sessionmaker() as session:
        rule = (
            await session.execute(
                select(models.NotificationRule)
                .where(models.NotificationRule.id == rule_id)
                .where(models.NotificationRule.chat_id == config.main_chat_id)
                .where(models.NotificationRule.event_type == event_type)
            )
        ).scalar_one_or_none()
        if not rule:
            await message.answer("Уведомление не найдено.", reply_markup=notify_rules_action_reply())
            return
        if action.startswith("удал"):
            await session.delete(rule)
            await session.commit()
            await message.answer("Уведомление удалено.", reply_markup=notify_rules_action_reply())
            return
        if action.startswith("откл"):
            rule.is_enabled = False
        elif action.startswith("вкл"):
            rule.is_enabled = True
        else:
            await message.answer(
                "Действие: включить, отключить или удалить.",
                reply_markup=notify_rules_action_reply(),
            )
            return
        await session.commit()
    await message.answer("Готово.", reply_markup=notify_rules_action_reply())


@router.message(AdminState.waiting_wipe_target)
async def wipe_target(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    if await _handle_admin_escape(message, state, config, sessionmaker, coc_client):
        return

    target_user = message.reply_to_message.from_user if message.reply_to_message else None
    target_text = (message.text or "").strip()

    async with sessionmaker() as session:
        if target_user:
            user = (
                await session.execute(
                    select(models.User).where(models.User.telegram_id == target_user.id)
                )
            ).scalar_one_or_none()
        elif target_text.startswith("@"):
            user = (
                await session.execute(
                    select(models.User).where(models.User.username == target_text.lstrip("@"))
                )
            ).scalar_one_or_none()
        else:
            user = (
                await session.execute(select(models.User).where(models.User.player_tag == target_text))
            ).scalar_one_or_none()

        if not user:
            await message.answer(
                "Пользователь не найден. Попробуйте ещё раз или нажмите «Назад».",
                reply_markup=admin_action_reply(),
            )
            return

        await session.execute(
            delete(models.TargetClaim).where(models.TargetClaim.claimed_by_telegram_id == user.telegram_id)
        )
        await session.execute(
            delete(models.WarParticipation).where(models.WarParticipation.telegram_id == user.telegram_id)
        )
        await session.execute(
            delete(models.CapitalContribution).where(models.CapitalContribution.telegram_id == user.telegram_id)
        )
        await session.execute(
            delete(models.StatsDaily).where(models.StatsDaily.telegram_id == user.telegram_id)
        )
        await session.delete(user)
        await session.commit()

    await state.clear()
    await message.answer(
        "Данные пользователя удалены.",
        reply_markup=admin_menu_reply(),
    )
