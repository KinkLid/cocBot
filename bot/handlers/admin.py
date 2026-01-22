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
    admin_whitelist_menu_reply,
    main_menu_reply,
)
from bot.keyboards.notify_inline import (
    admin_notify_main_kb,
    notify_delay_kb,
    notify_rule_edit_kb,
    notify_rule_list_kb,
    notify_rules_action_kb,
    notify_save_kb,
    notify_template_kb,
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
from bot.utils.notify_time import format_duration_ru_seconds
from bot.utils.state import reset_state_if_any
from bot.ui.renderers import chunk_message, render_cards, render_missed_attacks, short_name
from bot.utils.war_state import find_current_cwl_war, get_missed_attacks_label
from bot.utils.notification_rules import schedule_rule_for_active_event
from bot.utils.notification_templates import pack_rule_text, template_label, unpack_rule_text
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
    rule_action = State()
    rule_add = State()
    rule_add_text = State()
    rule_edit_text = State()
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


async def _toggle_chat_category(
    sessionmaker: async_sessionmaker,
    config: BotConfig,
    category: str,
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
        current = prefs.get(category, {})
        enabled = any(current.values())
        for key in current:
            current[key] = not enabled
        prefs[category] = current
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
    cards: list[str] = []
    for rule in rows:
        status = "🟢" if rule.is_enabled else "🔴"
        delay_text = format_duration_ru_seconds(rule.delay_seconds)
        template, description = unpack_rule_text(rule.custom_text)
        template_text = template_label(template) or "—"
        custom = short_name(description) or "—"
        line_one = f"{status} <b>#{html.escape(str(rule.id))}</b>"
        line_two = (
            f"└ ⏱ через {html.escape(delay_text)} • 🏷 {html.escape(template_text)}"
            f" • ✍️ {html.escape(custom)}"
        )
        cards.append(f"{line_one}\n{line_two}")
    return render_cards(cards) or "нет данных"


def _users_table(
    users: list[models.User],
    clan_joined: dict[str, datetime | None],
    zone: ZoneInfo,
) -> str:
    cards: list[str] = []
    for user in users:
        tg_name_raw = f"@{user.username}" if user.username else "без username"
        tg_name = html.escape(short_name(tg_name_raw))
        player_name = html.escape(short_name(user.player_name or "игрок"))
        tag_label = html.escape(user.player_tag or "")
        created_at = _format_datetime(user.created_at, zone)
        joined_at = clan_joined.get(user.player_tag.upper())
        if joined_at:
            joined_text = _format_datetime(joined_at, zone)
        elif user.first_seen_in_clan_at:
            joined_text = f"замечен с {_format_datetime(user.first_seen_in_clan_at, zone)}"
        else:
            joined_text = "—"
        name_line = f"👤 <b>{player_name}</b>"
        if tag_label:
            name_line += f" <code>{tag_label}</code>"
        line_two = (
            "└ "
            f"👤 {tg_name} • 🆔 <code>{html.escape(str(user.telegram_id))}</code> "
            f"• 🗓 {html.escape(created_at)} • 🏰 {html.escape(joined_text)}"
        )
        cards.append(f"{name_line}\n{line_two}")
    return render_cards(cards)


async def _load_clan_members(coc_client: CocClient, clan_tag: str) -> list[dict]:
    data = await coc_client.get_clan_members(clan_tag)
    members = data.get("items", [])
    return sorted(members, key=lambda member: member.get("clanRank") or 0)


def _blacklist_table(entries: list[models.BlacklistPlayer], zone: ZoneInfo) -> str:
    cards: list[str] = []
    for entry in entries:
        created_at = _format_datetime(entry.created_at, zone)
        reason = short_name(entry.reason)
        line_one = f"🚫 <b>{html.escape(entry.player_tag)}</b> — {html.escape(reason)}"
        line_two = (
            f"└ 👮 <code>{html.escape(str(entry.added_by_admin_id))}</code> "
            f"• 🗓 {html.escape(created_at)}"
        )
        cards.append(f"{line_one}\n{line_two}")
    return render_cards(cards) or "нет данных"


def _whitelist_table(entries: list[models.WhitelistPlayer], zone: ZoneInfo) -> str:
    cards: list[str] = []
    for entry in entries:
        created_at = _format_datetime(entry.created_at, zone)
        name = short_name(entry.player_name)
        comment = short_name(entry.comment)
        line_one = (
            f"✅ <b>{html.escape(entry.player_tag)}</b> — {html.escape(name)}"
        )
        line_two = (
            f"└ 👮 <code>{html.escape(str(entry.added_by_admin_id))}</code> "
            f"• 🗓 {html.escape(created_at)} • 💬 {html.escape(comment)}"
        )
        cards.append(f"{line_one}\n{line_two}")
    return render_cards(cards) or "нет данных"


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
        prefs = await _get_chat_prefs(sessionmaker, config)
        await message.answer(
            "Настройки уведомлений (чат).",
            reply_markup=admin_notify_main_kb(prefs),
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
        prefs = await _get_chat_prefs(sessionmaker, config)
        await message.answer(
            "Настройки уведомлений (чат).",
            reply_markup=admin_notify_main_kb(prefs),
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
    prefs = await _get_chat_prefs(sessionmaker, config)
    await message.answer("Настройки уведомлений (чат).", reply_markup=admin_notify_main_kb(prefs))
    await send_hint_once(
        message,
        sessionmaker,
        message.from_user.id,
        "seen_hint_admin_notify",
        ADMIN_NOTIFY_HINT,
    )




@router.message(F.text.in_(label_variants("admin_notify_chat")))
async def admin_notify_chat_menu(
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
    prefs = await _get_chat_prefs(sessionmaker, config)
    await message.answer(
        "Настройки уведомлений (чат).",
        reply_markup=admin_notify_main_kb(prefs),
    )


@router.callback_query(F.data.startswith("an:"))
async def admin_notify_callbacks(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if not is_admin(callback.from_user.id, config):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    if len(parts) < 2:
        await callback.answer()
        return
    action = parts[1]
    if action in {"menu", "back", "rules", "list", "add", "action", "pick", "pickdel"}:
        await reset_state_if_any(state)
    if action == "back":
        missed_label = await get_missed_attacks_label(coc_client, config.clan_tag)
        await callback.message.answer(
            "Админ-панель.",
            reply_markup=admin_menu_reply(missed_label),
        )
        await callback.message.edit_text("Настройки закрыты.")
        await callback.answer()
        return
    if action == "menu":
        prefs = await _get_chat_prefs(sessionmaker, config)
        await callback.message.edit_text(
            "Настройки уведомлений (чат).",
            reply_markup=admin_notify_main_kb(prefs),
        )
        await callback.answer()
        return
    if action == "toggle":
        if len(parts) < 3:
            await callback.answer()
            return
        category = parts[2]
        prefs = await _toggle_chat_category(sessionmaker, config, category)
        await callback.message.edit_text(
            "Настройки уведомлений (чат).",
            reply_markup=admin_notify_main_kb(prefs),
        )
        await callback.answer("✅ Сохранено")
        return
    if action == "rules":
        if len(parts) < 3:
            await callback.answer()
            return
        event_type = parts[2]
        if event_type not in ADMIN_EVENT_LABELS:
            await callback.answer()
            return
        await state.update_data(rule_event_type=event_type)
        await state.set_state(AdminState.rule_action)
        await callback.message.edit_text(
            f"Управление уведомлениями: {ADMIN_EVENT_LABELS[event_type]}.",
            reply_markup=notify_rules_action_kb("an", event_type),
        )
        await callback.answer()
        return
    if action == "action":
        if len(parts) < 3:
            await callback.answer()
            return
        event_type = parts[2]
        await state.update_data(rule_event_type=event_type)
        await state.set_state(AdminState.rule_action)
        await callback.message.edit_text(
            f"Управление уведомлениями: {ADMIN_EVENT_LABELS.get(event_type, event_type)}.",
            reply_markup=notify_rules_action_kb("an", event_type),
        )
        await callback.answer()
        return
    if action == "add":
        if len(parts) < 3:
            await callback.answer()
            return
        event_type = parts[2]
        await state.update_data(
            rule_event_type=event_type,
            rule_delay_seconds=0,
            rule_template=None,
            rule_text=None,
            rule_delay_mode="add",
        )
        await state.set_state(AdminState.rule_add)
        await callback.message.edit_text(
            "Выберите тип события.",
            reply_markup=notify_template_kb("an", event_type),
        )
        await callback.answer()
        return
    if action == "tmpl":
        if len(parts) < 3:
            await callback.answer()
            return
        template_key = parts[2]
        state_data = await state.get_data()
        event_type = state_data.get("rule_event_type")
        if event_type not in ADMIN_EVENT_LABELS:
            await callback.answer()
            return
        await state.update_data(rule_template=template_key, rule_delay_seconds=0)
        await callback.message.edit_text(
            "Настройте задержку уведомления.",
            reply_markup=notify_delay_kb("an", event_type, 0),
        )
        await callback.answer("⏱ Задержка: 0m")
        return
    if action == "delay":
        if len(parts) < 3:
            await callback.answer()
            return
        step = parts[2]
        state_data = await state.get_data()
        event_type = state_data.get("rule_event_type")
        delay_seconds = int(state_data.get("rule_delay_seconds", 0))
        if step == "reset":
            delay_seconds = 0
        elif step == "done":
            if state_data.get("rule_delay_mode") == "edit":
                rule_id = state_data.get("rule_edit_id")
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
                        await callback.answer("Уведомление не найдено.", show_alert=True)
                        return
                    rule.delay_seconds = delay_seconds
                    await session.commit()
                await state.clear()
                await callback.message.edit_text(
                    "✅ Задержка обновлена.",
                    reply_markup=notify_rule_edit_kb("an", event_type, rule_id, rule.is_enabled),
                )
                await callback.answer("✅ Сохранено")
                return
            await callback.message.edit_text(
                f"⏱ Задержка: {format_duration_ru_seconds(delay_seconds)}",
                reply_markup=notify_save_kb("an", event_type, bool(state_data.get("rule_text"))),
            )
            await callback.answer("✅ Готово")
            return
        else:
            try:
                delta = int(step)
            except ValueError:
                await callback.answer()
                return
            delay_seconds = max(0, delay_seconds + delta)
        await state.update_data(rule_delay_seconds=delay_seconds)
        await callback.message.edit_text(
            f"⏱ Задержка: {format_duration_ru_seconds(delay_seconds)}",
            reply_markup=notify_delay_kb("an", event_type, delay_seconds),
        )
        await callback.answer()
        return
    if action == "text":
        await state.set_state(AdminState.rule_add_text)
        await callback.message.answer("Введите текст уведомления одним сообщением.")
        await callback.answer()
        return
    if action == "save":
        state_data = await state.get_data()
        event_type = state_data.get("rule_event_type")
        delay_seconds = int(state_data.get("rule_delay_seconds", 0))
        template_key = state_data.get("rule_template")
        description = state_data.get("rule_text")
        if event_type not in ADMIN_EVENT_LABELS:
            await callback.answer()
            return
        custom_text = pack_rule_text(template_key, description)
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
        await state.clear()
        await callback.message.edit_text(
            f"Создано: {template_label(template_key) or 'Событие'} • "
            f"⏱ {format_duration_ru_seconds(delay_seconds)} • статус: включено",
            reply_markup=notify_rules_action_kb("an", event_type),
        )
        await callback.answer("✅ Сохранено")
        return
    if action == "list":
        if len(parts) < 4:
            await callback.answer()
            return
        event_type = parts[2]
        page = max(int(parts[3]), 1)
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
            await callback.message.edit_text(
                "Активных уведомлений нет.",
                reply_markup=notify_rules_action_kb("an", event_type),
            )
            await callback.answer()
            return
        page_size = 5
        start = (page - 1) * page_size
        end = start + page_size
        total_pages = max(1, (len(rules) + page_size - 1) // page_size)
        visible = rules[start:end]
        await callback.message.edit_text(
            f"Уведомления: {ADMIN_EVENT_LABELS[event_type]}.\n{_rules_table(visible)}",
            reply_markup=notify_rule_list_kb("an", event_type, visible, page, total_pages),
            parse_mode=ParseMode.HTML,
        )
        await callback.answer()
        return
    if action in {"pick", "pickdel"}:
        if len(parts) < 3:
            await callback.answer()
            return
        event_type = parts[2]
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
            await callback.message.edit_text(
                "Активных уведомлений нет.",
                reply_markup=notify_rules_action_kb("an", event_type),
            )
            await callback.answer()
            return
        page_size = 5
        visible = rules[:page_size]
        total_pages = max(1, (len(rules) + page_size - 1) // page_size)
        await callback.message.edit_text(
            f"Выберите уведомление для действия.\n{_rules_table(visible)}",
            reply_markup=notify_rule_list_kb("an", event_type, visible, 1, total_pages),
            parse_mode=ParseMode.HTML,
        )
        await callback.answer()
        return
    if action in {"edit", "toggle", "delete", "editdelay", "edittext"}:
        if len(parts) < 4:
            await callback.answer()
            return
        event_type = parts[2]
        rule_id = int(parts[3])
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
                await callback.answer("Уведомление не найдено.", show_alert=True)
                return
            if action == "toggle":
                rule.is_enabled = not rule.is_enabled
                await session.commit()
                status_text = "🔔 Включено" if rule.is_enabled else "🔕 Выключено"
                await callback.answer(status_text)
                await callback.message.edit_text(
                    status_text,
                    reply_markup=notify_rule_edit_kb("an", event_type, rule.id, rule.is_enabled),
                )
                return
            if action == "delete":
                await session.delete(rule)
                await session.commit()
                await callback.answer("🗑 Удалено")
                await callback.message.edit_text(
                    "Уведомление удалено.",
                    reply_markup=notify_rules_action_kb("an", event_type),
                )
                return
            if action == "edit":
                await state.update_data(rule_edit_id=rule.id, rule_event_type=event_type)
                await callback.message.edit_text(
                    f"Уведомление #{rule.id}.",
                    reply_markup=notify_rule_edit_kb("an", event_type, rule.id, rule.is_enabled),
                )
                await callback.answer()
                return
            if action == "editdelay":
                await state.update_data(rule_edit_id=rule.id, rule_event_type=event_type)
                await state.set_state(AdminState.rule_add)
                await state.update_data(rule_delay_seconds=rule.delay_seconds, rule_delay_mode="edit")
                await callback.message.edit_text(
                    f"⏱ Задержка: {format_duration_ru_seconds(rule.delay_seconds)}",
                    reply_markup=notify_delay_kb("an", event_type, rule.delay_seconds),
                )
                await callback.answer()
                return
            if action == "edittext":
                await state.update_data(rule_edit_id=rule.id, rule_event_type=event_type)
                await state.set_state(AdminState.rule_edit_text)
                await callback.message.answer("Введите новый текст уведомления одним сообщением.")
                await callback.answer()
                return
    await callback.answer()


@router.message(AdminState.rule_add_text)
async def admin_rule_add_text(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if await _handle_admin_escape(message, state, config, sessionmaker, coc_client):
        return
    text = (message.text or "").strip()
    await state.update_data(rule_text=text)
    state_data = await state.get_data()
    delay_seconds = int(state_data.get("rule_delay_seconds", 0))
    event_type = state_data.get("rule_event_type")
    await message.answer(
        f"⏱ Задержка: {format_duration_ru_seconds(delay_seconds)}",
        reply_markup=notify_save_kb("an", event_type, True),
    )


@router.message(AdminState.rule_edit_text)
async def admin_rule_edit_text_input(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if await _handle_admin_escape(message, state, config, sessionmaker, coc_client):
        return
    data = await state.get_data()
    rule_id = data.get("rule_edit_id")
    event_type = data.get("rule_event_type")
    if not rule_id or event_type not in ADMIN_EVENT_LABELS:
        await state.clear()
        missed_label = await get_missed_attacks_label(coc_client, config.clan_tag)
        await message.answer("Админ-панель.", reply_markup=admin_menu_reply(missed_label))
        return
    text = (message.text or "").strip()
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
            await message.answer("Уведомление не найдено.")
            await state.clear()
            return
        template_key, _ = unpack_rule_text(rule.custom_text)
        rule.custom_text = pack_rule_text(template_key, text)
        await session.commit()
    await state.clear()
    await message.answer(
        "✅ Сохранено.",
        reply_markup=notify_rule_edit_kb("an", event_type, rule_id, rule.is_enabled),
    )


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
