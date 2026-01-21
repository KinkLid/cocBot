from __future__ import annotations

import logging
from datetime import datetime, timezone
import html
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
    admin_blacklist_menu_reply,
    admin_action_reply,
    admin_menu_reply,
    admin_notify_category_reply,
    admin_notify_menu_reply,
    admin_whitelist_menu_reply,
    main_menu_reply,
    notify_rules_action_reply,
    notify_rules_type_reply,
)
from bot.keyboards.blacklist import blacklist_members_kb
from bot.services.commands import register_bot_commands
from bot.services.coc_client import CocClient
from bot.services.hints import send_hint_once
from bot.services.notifications import NotificationService, normalize_chat_prefs
from bot.services.permissions import is_admin
from bot.texts.hints import ADMIN_NOTIFY_HINT
from bot.ui.labels import is_back, is_main_menu, label, label_variants
from bot.utils.coc_time import parse_coc_time
from bot.utils.navigation import pop_menu, reset_menu, set_menu
from bot.utils.notify_time import format_duration_ru_seconds, parse_duration
from bot.utils.state import reset_state_if_any
from bot.utils.tables import build_pre_table
from bot.ui.renderers import chunk_message, render_missed_attacks
from bot.utils.war_state import find_current_cwl_war, get_missed_attacks_label
from bot.utils.notification_rules import schedule_rule_for_active_event
from bot.utils.validators import is_valid_tag, normalize_tag

logger = logging.getLogger(__name__)
router = Router()

USERS_PAGE_SIZE = 10
BLACKLIST_PAGE_SIZE = 10
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
    blacklist_add_tag = State()
    blacklist_add_reason = State()
    blacklist_remove_tag = State()
    whitelist_add_tag = State()
    whitelist_add_comment = State()
    whitelist_remove_tag = State()


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
        delay_text = format_duration_ru_seconds(rule.delay_seconds)
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
    lines: list[str] = []
    for user in users:
        tg_name_raw = f"@{user.username}" if user.username else "без username"
        tg_name = html.escape(tg_name_raw)
        player_name = html.escape(user.player_name or "игрок")
        tag_label = html.escape(user.player_tag or "")
        created_at = _format_datetime(user.created_at, zone)
        joined_at = clan_joined.get(user.player_tag.upper())
        if joined_at:
            joined_text = _format_datetime(joined_at, zone)
        elif user.first_seen_in_clan_at:
            joined_text = f"замечен с {_format_datetime(user.first_seen_in_clan_at, zone)}"
        else:
            joined_text = "—"
        name_line = f"• <b>{player_name}</b>"
        if tag_label:
            name_line += f" <code>{tag_label}</code>"
        lines.append(name_line)
        lines.append(f"  👤 Telegram: <b>{tg_name}</b>")
        lines.append(f"  🆔 ID: <code>{user.telegram_id}</code>")
        lines.append(f"  🗓 Регистрация: {created_at}")
        lines.append(f"  🏰 Клан: {joined_text}")
        lines.append("")
    return "\n".join(lines).strip()


async def _load_clan_members(coc_client: CocClient, clan_tag: str) -> list[dict]:
    data = await coc_client.get_clan_members(clan_tag)
    members = data.get("items", [])
    return sorted(members, key=lambda member: member.get("clanRank") or 0)


def _blacklist_table(entries: list[models.BlacklistPlayer], zone: ZoneInfo) -> str:
    rows: list[list[str]] = []
    for entry in entries:
        created_at = _format_datetime(entry.created_at, zone)
        reason = entry.reason or "—"
        rows.append([entry.player_tag, reason, str(entry.added_by_admin_id), created_at])
    return build_pre_table(
        ["Тег", "Причина", "Админ", "Дата"],
        rows,
        max_widths=[14, 24, 12, 16],
    )


def _whitelist_table(entries: list[models.WhitelistPlayer], zone: ZoneInfo) -> str:
    rows: list[list[str]] = []
    for entry in entries:
        created_at = _format_datetime(entry.created_at, zone)
        name = entry.player_name or "—"
        comment = entry.comment or "—"
        rows.append(
            [
                str(entry.id),
                entry.player_tag,
                name,
                str(entry.added_by_admin_id),
                created_at,
                comment,
            ]
        )
    return build_pre_table(
        ["ID", "Тег", "Имя", "Админ", "Дата", "Комментарий"],
        rows,
        max_widths=[6, 14, 16, 12, 16, 24],
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
    buttons.append([InlineKeyboardButton(text=label("back"), callback_data="admin_users:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _handle_admin_escape(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> bool:
    if is_main_menu(message.text):
        await reset_state_if_any(state)
        await reset_menu(state)
        await message.answer(
            "Главное меню.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return True
    if is_back(message.text):
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
    if current == "admin_blacklist":
        await message.answer("Чёрный список.", reply_markup=admin_blacklist_menu_reply())
        return
    if current == "admin_whitelist":
        await message.answer("Вайтлист игроков.", reply_markup=admin_whitelist_menu_reply())
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


@router.message(Command("update_commands"))
async def update_commands_command(
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
    await register_bot_commands(message.bot)
    await message.answer("Список команд обновлён.", reply_markup=admin_menu_reply())


@router.message(F.text.in_(label_variants("admin")))
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


@router.message(Command("admin"))
async def admin_panel_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
) -> None:
    await admin_panel_button(message, state, config, coc_client)


@router.message(F.text.in_(label_variants("admin_clear_player")))
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


@router.message(F.text.in_(label_variants("admin_diagnostics")))
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
    header = f"<b>👥 Пользователи</b> (страница {page}/{total_pages})"
    text = "\n".join([header, table]) if table else header
    for index, chunk in enumerate(chunk_message(text)):
        await message.answer(
            chunk,
            reply_markup=_users_pagination_kb(page, total_pages) if index == 0 else None,
            parse_mode=ParseMode.HTML,
        )


@router.message(F.text.in_(label_variants("admin_users")))
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


@router.message(Command("users"))
async def admin_users_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    await admin_users_button(message, state, config, sessionmaker, coc_client)


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


@router.message(F.text.in_(label_variants("admin_blacklist")))
async def admin_blacklist_menu(
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
    await set_menu(state, "admin_blacklist")
    await message.answer("Чёрный список.", reply_markup=admin_blacklist_menu_reply())


@router.message(F.text.in_(label_variants("admin_whitelist")))
async def admin_whitelist_menu(
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
    await set_menu(state, "admin_whitelist")
    await message.answer("Вайтлист игроков.", reply_markup=admin_whitelist_menu_reply())


@router.message(F.text.in_(label_variants("blacklist_add")))
async def admin_blacklist_add_start(
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
    await state.set_state(AdminState.blacklist_add_tag)
    try:
        members = await _load_clan_members(coc_client, config.clan_tag)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load clan members for blacklist: %s", exc)
        members = []
    if members:
        await message.answer(
            "Выберите игрока из списка или пришлите тег вручную.",
            reply_markup=blacklist_members_kb(members, page=1, page_size=BLACKLIST_PAGE_SIZE),
        )
    else:
        await message.answer(
            "Пришлите тег игрока для ЧС.",
            reply_markup=admin_action_reply(),
        )


@router.callback_query(F.data.startswith("blacklist:page:"))
async def admin_blacklist_page(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
) -> None:
    await callback.answer()
    if not is_admin(callback.from_user.id, config):
        if callback.message:
            await callback.message.answer("Админ-панель доступна только администраторам.")
        return
    try:
        page = int((callback.data or "").split(":")[-1])
    except ValueError:
        return
    try:
        members = await _load_clan_members(coc_client, config.clan_tag)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to reload clan members for blacklist: %s", exc)
        return
    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=blacklist_members_kb(members, page=page, page_size=BLACKLIST_PAGE_SIZE)
        )


@router.callback_query(F.data == "blacklist:cancel")
async def admin_blacklist_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
) -> None:
    await callback.answer("Отменено")
    await reset_state_if_any(state)
    if not is_admin(callback.from_user.id, config):
        return
    await callback.message.answer("Чёрный список.", reply_markup=admin_blacklist_menu_reply())


@router.callback_query(F.data.startswith("blacklist:target:"))
async def admin_blacklist_pick_target(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
) -> None:
    await callback.answer()
    if not is_admin(callback.from_user.id, config):
        if callback.message:
            await callback.message.answer("Админ-панель доступна только администраторам.")
        return
    tag = (callback.data or "").split(":", 2)[-1]
    normalized_tag = normalize_tag(tag)
    if not is_valid_tag(normalized_tag):
        if callback.message:
            await callback.message.answer("Некорректный тег. Попробуйте ещё раз.")
        return
    await state.set_state(AdminState.blacklist_add_reason)
    await state.update_data(blacklist_player_tag=normalized_tag)
    if callback.message:
        await callback.message.answer(
            f"Введите причину для ЧС (или напишите «без причины»):",
            reply_markup=admin_action_reply(),
        )


@router.message(AdminState.blacklist_add_tag)
async def admin_blacklist_add_tag(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if await _handle_admin_escape(message, state, config, sessionmaker, coc_client):
        return
    tag = normalize_tag(message.text or "")
    if not is_valid_tag(tag):
        await message.answer(
            "Некорректный тег. Пример: #ABC123",
            reply_markup=admin_action_reply(),
        )
        return
    await state.set_state(AdminState.blacklist_add_reason)
    await state.update_data(blacklist_player_tag=tag)
    await message.answer(
        "Введите причину для ЧС (или напишите «без причины»):",
        reply_markup=admin_action_reply(),
    )


@router.message(AdminState.blacklist_add_reason)
async def admin_blacklist_add_reason(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if await _handle_admin_escape(message, state, config, sessionmaker, coc_client):
        return
    data = await state.get_data()
    player_tag = data.get("blacklist_player_tag")
    if not player_tag:
        await reset_state_if_any(state)
        await message.answer("Не удалось определить игрока.", reply_markup=admin_blacklist_menu_reply())
        return
    reason_text = (message.text or "").strip()
    reason = None if reason_text.lower() == "без причины" else reason_text
    async with sessionmaker() as session:
        entry = (
            await session.execute(
                select(models.BlacklistPlayer).where(models.BlacklistPlayer.player_tag == player_tag)
            )
        ).scalar_one_or_none()
        if entry:
            entry.reason = reason
            entry.added_by_admin_id = message.from_user.id
            entry.created_at = datetime.now(timezone.utc)
            entry.is_active = True
        else:
            session.add(
                models.BlacklistPlayer(
                    player_tag=player_tag,
                    reason=reason,
                    added_by_admin_id=message.from_user.id,
                    created_at=datetime.now(timezone.utc),
                    is_active=True,
                )
            )
        await session.commit()
    await reset_state_if_any(state)
    await message.answer(
        f"Игрок {html.escape(player_tag)} добавлен в ЧС.",
        reply_markup=admin_blacklist_menu_reply(),
        parse_mode=ParseMode.HTML,
    )


@router.message(F.text.in_(label_variants("blacklist_show")))
async def admin_blacklist_list(
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
        entries = (
            await session.execute(
                select(models.BlacklistPlayer)
                .where(models.BlacklistPlayer.is_active.is_(True))
                .order_by(models.BlacklistPlayer.created_at.desc())
            )
        ).scalars().all()
    if not entries:
        await message.answer("Чёрный список пуст.", reply_markup=admin_blacklist_menu_reply())
        return
    zone = ZoneInfo(config.timezone)
    table = _blacklist_table(entries, zone)
    await message.answer(
        f"Активные записи ЧС: {len(entries)}.\n{table}",
        reply_markup=admin_blacklist_menu_reply(),
        parse_mode=ParseMode.HTML,
    )


@router.message(F.text.in_(label_variants("blacklist_remove")))
async def admin_blacklist_remove_start(
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
    await state.set_state(AdminState.blacklist_remove_tag)
    await message.answer(
        "Пришлите тег игрока для удаления из ЧС.",
        reply_markup=admin_action_reply(),
    )


@router.message(AdminState.blacklist_remove_tag)
async def admin_blacklist_remove(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if await _handle_admin_escape(message, state, config, sessionmaker, coc_client):
        return
    tag = normalize_tag(message.text or "")
    if not is_valid_tag(tag):
        await message.answer("Некорректный тег. Пример: #ABC123", reply_markup=admin_action_reply())
        return
    async with sessionmaker() as session:
        entry = (
            await session.execute(
                select(models.BlacklistPlayer)
                .where(models.BlacklistPlayer.player_tag == tag)
                .where(models.BlacklistPlayer.is_active.is_(True))
            )
        ).scalar_one_or_none()
        if not entry:
            await message.answer("Игрок не найден в активном ЧС.", reply_markup=admin_blacklist_menu_reply())
            return
        entry.is_active = False
        await session.commit()
    await reset_state_if_any(state)
    await message.answer(
        f"Игрок {html.escape(tag)} удалён из ЧС.",
        reply_markup=admin_blacklist_menu_reply(),
        parse_mode=ParseMode.HTML,
    )


@router.message(F.text.in_(label_variants("whitelist_add")))
async def admin_whitelist_add_start(
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
    await state.set_state(AdminState.whitelist_add_tag)
    await message.answer(
        "Введите player tag (например #ABC123).",
        reply_markup=admin_action_reply(),
    )


@router.message(AdminState.whitelist_add_tag)
async def admin_whitelist_add_tag(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if await _handle_admin_escape(message, state, config, sessionmaker, coc_client):
        return
    tag = normalize_tag(message.text or "")
    if not is_valid_tag(tag):
        await message.answer("Некорректный тег. Пример: #ABC123", reply_markup=admin_action_reply())
        return
    await state.update_data(whitelist_player_tag=tag)
    await state.set_state(AdminState.whitelist_add_comment)
    await message.answer(
        "Введите комментарий (или напишите «без комментария»):",
        reply_markup=admin_action_reply(),
    )


@router.message(AdminState.whitelist_add_comment)
async def admin_whitelist_add_comment(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if await _handle_admin_escape(message, state, config, sessionmaker, coc_client):
        return
    data = await state.get_data()
    player_tag = data.get("whitelist_player_tag")
    if not player_tag:
        await reset_state_if_any(state)
        await message.answer("Не удалось обработать тег.", reply_markup=admin_whitelist_menu_reply())
        return
    comment_text = (message.text or "").strip()
    comment = None if comment_text.lower() == "без комментария" else comment_text
    player_name = None
    try:
        player = await coc_client.get_player(player_tag)
        player_name = player.get("name")
    except Exception:  # noqa: BLE001
        player_name = None
    async with sessionmaker() as session:
        entry = (
            await session.execute(
                select(models.WhitelistPlayer).where(models.WhitelistPlayer.player_tag == player_tag)
            )
        ).scalar_one_or_none()
        if entry:
            entry.comment = comment
            if player_name:
                entry.player_name = player_name
            entry.added_by_admin_id = message.from_user.id
            entry.created_at = datetime.now(timezone.utc)
            entry.is_active = True
        else:
            session.add(
                models.WhitelistPlayer(
                    player_tag=player_tag,
                    player_name=player_name,
                    comment=comment,
                    added_by_admin_id=message.from_user.id,
                    created_at=datetime.now(timezone.utc),
                    is_active=True,
                )
            )
        await session.commit()
    await reset_state_if_any(state)
    await message.answer(
        f"Игрок {html.escape(player_tag)} добавлен в вайтлист.",
        reply_markup=admin_whitelist_menu_reply(),
        parse_mode=ParseMode.HTML,
    )


@router.message(F.text.in_(label_variants("whitelist_show")))
async def admin_whitelist_list(
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
    async with sessionmaker() as session:
        entries = (
            await session.execute(
                select(models.WhitelistPlayer)
                .where(models.WhitelistPlayer.is_active.is_(True))
                .order_by(models.WhitelistPlayer.created_at.desc())
            )
        ).scalars().all()
        updated_entries: list[models.WhitelistPlayer] = []
        for entry in entries:
            if entry.player_name:
                continue
            try:
                player = await coc_client.get_player(entry.player_tag)
            except Exception:  # noqa: BLE001
                continue
            name = player.get("name")
            if name:
                entry.player_name = name
                updated_entries.append(entry)
        if updated_entries:
            await session.commit()
    if not entries:
        await message.answer("Вайтлист пуст.", reply_markup=admin_whitelist_menu_reply())
        return
    zone = ZoneInfo(config.timezone)
    table = _whitelist_table(entries, zone)
    await message.answer(
        f"Активные игроки: {len(entries)}.\n{table}",
        reply_markup=admin_whitelist_menu_reply(),
        parse_mode=ParseMode.HTML,
    )


@router.message(F.text.in_(label_variants("whitelist_remove")))
async def admin_whitelist_remove_start(
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
    await state.set_state(AdminState.whitelist_remove_tag)
    await message.answer(
        "Пришлите ID записи или player tag.",
        reply_markup=admin_action_reply(),
    )


@router.message(AdminState.whitelist_remove_tag)
async def admin_whitelist_remove(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if await _handle_admin_escape(message, state, config, sessionmaker, coc_client):
        return
    raw_value = (message.text or "").strip()
    if not raw_value:
        await message.answer("Нужно указать ID или tag.", reply_markup=admin_action_reply())
        return
    async with sessionmaker() as session:
        entry = None
        if raw_value.isdigit():
            entry = (
                await session.execute(
                    select(models.WhitelistPlayer)
                    .where(models.WhitelistPlayer.id == int(raw_value))
                    .where(models.WhitelistPlayer.is_active.is_(True))
                )
            ).scalar_one_or_none()
        else:
            tag = normalize_tag(raw_value)
            entry = (
                await session.execute(
                    select(models.WhitelistPlayer)
                    .where(models.WhitelistPlayer.player_tag == tag)
                    .where(models.WhitelistPlayer.is_active.is_(True))
                )
            ).scalar_one_or_none()
        if not entry:
            await message.answer("Игрок не найден в вайтлисте.", reply_markup=admin_whitelist_menu_reply())
            return
        entry.is_active = False
        await session.commit()
    await reset_state_if_any(state)
    await message.answer(
        f"Игрок {html.escape(entry.player_tag)} удалён из вайтлиста.",
        reply_markup=admin_whitelist_menu_reply(),
        parse_mode=ParseMode.HTML,
    )


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
        text = render_missed_attacks(
            "🏰 ЛВК: кто не атаковал",
            cwl_war,
            config.clan_tag,
            include_overview=True,
        )
        for index, chunk in enumerate(chunk_message(text)):
            await message.answer(
                chunk,
                reply_markup=admin_menu_reply() if index == 0 else None,
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
    text = render_missed_attacks(
        "⚔️ КВ: кто не атаковал",
        war,
        config.clan_tag,
        include_overview=True,
    )
    for index, chunk in enumerate(chunk_message(text)):
        await message.answer(
            chunk,
            reply_markup=admin_menu_reply() if index == 0 else None,
            parse_mode=ParseMode.HTML,
        )


@router.message(Command("missed"))
async def admin_missed_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
) -> None:
    await admin_missed_attacks_now(message, state, config, coc_client)


@router.message(F.text.in_(label_variants("back")))
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


@router.message(F.text.in_(label_variants("admin_notify")))
async def admin_notify_menu(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await _show_admin_notify_menu(message, state, config, sessionmaker)


@router.message(Command("set_chat_notify"))
async def admin_notify_menu_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await _show_admin_notify_menu(message, state, config, sessionmaker)


async def _show_admin_notify_menu(
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
    await set_menu(state, "admin_notify_menu")
    await message.answer("Уведомления: общий чат.", reply_markup=admin_notify_menu_reply())
    await send_hint_once(
        message,
        sessionmaker,
        message.from_user.id,
        "seen_hint_admin_notify",
        ADMIN_NOTIFY_HINT,
    )


@router.message(
    F.text.in_(
        label_variants("admin_notify_war")
        | label_variants("admin_notify_cwl")
        | label_variants("admin_notify_capital")
    )
)
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
    base_map = {
        "admin_notify_war": ("war", "admin_notify_war"),
        "admin_notify_cwl": ("cwl", "admin_notify_cwl"),
        "admin_notify_capital": ("capital", "admin_notify_capital"),
    }
    category_map: dict[str, tuple[str, str]] = {}
    for key, value in base_map.items():
        for variant in label_variants(key):
            category_map[variant] = value
    category, menu_key = category_map.get(message.text or "", (None, None))
    if not category:
        return
    prefs = await _get_chat_prefs(sessionmaker, config)
    await set_menu(state, menu_key)
    await message.answer(
        "Настройки уведомлений.",
        reply_markup=admin_notify_category_reply(category, prefs.get(category, {})),
    )


@router.message(
    F.text.startswith("✅ КВ:")
    | F.text.startswith("🔴 КВ:")
    | F.text.startswith("✅ ЛВК:")
    | F.text.startswith("🔴 ЛВК:")
    | F.text.startswith("✅ Столица:")
    | F.text.startswith("🔴 Столица:")
    | F.text.startswith("✅ Итоги месяца")
    | F.text.startswith("🔴 Итоги месяца")
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
    for prefix in ("✅ ", "🔴 "):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
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


@router.message(F.text.in_(label_variants("admin_notify_chat")))
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
    await send_hint_once(
        message,
        sessionmaker,
        message.from_user.id,
        "seen_hint_admin_notify",
        ADMIN_NOTIFY_HINT,
    )
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
    if is_back(message.text):
        missed_label = await get_missed_attacks_label(coc_client, config.clan_tag)
        await message.answer("Админ-панель.", reply_markup=admin_menu_reply(missed_label))
        await state.clear()
        return
    event_type_map: dict[str, str] = {}
    for key, value in {
        "notify_type_war": "war",
        "notify_type_cwl": "cwl",
        "notify_type_capital": "capital",
    }.items():
        for variant in label_variants(key):
            event_type_map[variant] = value
    event_type = event_type_map.get(message.text or "")
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
    if is_back(message.text):
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
    if message.text in label_variants("notify_add"):
        await state.set_state(AdminState.rule_delay_value)
        await message.answer(
            "Введите задержку, например: 17h 2m 34s (h — часы, m — минуты, s — секунды).",
            reply_markup=notify_rules_action_reply(),
        )
        return
    if message.text in label_variants("notify_list"):
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
    if message.text in label_variants("notify_edit"):
        await state.set_state(AdminState.rule_edit_id)
        await message.answer("Введите ID уведомления для изменения.", reply_markup=notify_rules_action_reply())
        return
    if message.text in label_variants("notify_delete"):
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
    if is_back(message.text):
        await state.set_state(AdminState.rule_action)
        await message.answer("Выберите действие.", reply_markup=notify_rules_action_reply())
        return
    delay_seconds = parse_duration(message.text or "")
    if not delay_seconds:
        await message.answer(
            "Нужен формат: 17h 2m 34s (h — часы, m — минуты, s — секунды).",
            reply_markup=notify_rules_action_reply(),
        )
        return
    await state.update_data(rule_delay_seconds=delay_seconds)
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
    if is_back(message.text):
        await state.set_state(AdminState.rule_action)
        await message.answer("Выберите действие.", reply_markup=notify_rules_action_reply())
        return
    data = await state.get_data()
    event_type = data.get("rule_event_type")
    delay_seconds = data.get("rule_delay_seconds")
    if event_type not in {"war", "cwl", "capital"} or not delay_seconds:
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
            delay_seconds=delay_seconds,
            custom_text=custom_text,
            is_enabled=True,
        )
        session.add(rule)
        await session.flush()
        await schedule_rule_for_active_event(session, coc_client, config, rule)
        await session.commit()
    await state.set_state(AdminState.rule_action)
    await message.answer(
        f"Уведомление добавлено: через {format_duration_ru_seconds(delay_seconds)}.",
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
    if is_back(message.text):
        await state.set_state(AdminState.rule_action)
        await message.answer("Выберите действие.", reply_markup=notify_rules_action_reply())
        return
    if not (message.text or "").isdigit():
        await message.answer("Нужен числовой ID.", reply_markup=notify_rules_action_reply())
        return
    await state.update_data(rule_edit_id=int(message.text))
    await state.set_state(AdminState.rule_edit_delay)
    await message.answer(
        "Введите новую задержку (17h 2m, 90m 10s) или '-' чтобы оставить.",
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
    if is_back(message.text):
        await state.set_state(AdminState.rule_action)
        await message.answer("Выберите действие.", reply_markup=notify_rules_action_reply())
        return
    text = (message.text or "").strip()
    delay_seconds = None
    if text != "-":
        delay_seconds = parse_duration(text)
        if not delay_seconds:
            await message.answer(
                "Нужен формат: 17h 2m 34s или '-'.",
                reply_markup=notify_rules_action_reply(),
            )
            return
    await state.update_data(rule_edit_delay=delay_seconds)
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
    if is_back(message.text):
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
            rule.delay_seconds = new_delay
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
    if is_back(message.text):
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
            delete(models.TargetClaim).where(models.TargetClaim.claimed_by_user_id == user.telegram_id)
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
