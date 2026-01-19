from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.handlers.complaints import start_complaint_flow
from bot.handlers.notify import notify_command, send_notify_menu
from bot.handlers.registration import start_registration
from bot.handlers.stats import mystats_command
from bot.handlers.targets import targets_command
from bot.keyboards.common import admin_menu_reply, main_menu_reply, profile_menu_reply
from bot.services.coc_client import CocClient
from bot.services.permissions import is_admin
from bot.texts.help import build_help_text
from bot.texts.rules import build_rules_text
from bot.utils.navigation import reset_menu, set_menu
from bot.utils.war_state import get_missed_attacks_label
from bot.utils.state import reset_state_if_any
from bot.utils.telegram import build_bot_dm_keyboard, build_bot_dm_link, try_send_dm

router = Router()
logger = logging.getLogger(__name__)

MENU_TEXT_ACTIONS = {
    "Регистрация": "register",
    "Мой профиль": "profile",
    "Моя статистика": "mystats",
    "🔔 Уведомления": "notify",
    "Уведомления": "notify",
    "Цели на войне": "targets",
    "📜 Правила клана": "rules",
    "Правила клана": "rules",
    "📣 Жалоба": "complaint",
    "Жалоба": "complaint",
    "Помощь / Гайд": "guide",
    "Помощь гайд": "guide",
    "Админ-панель": "admin",
    "Админ панель": "admin",
}


@router.message(CommandStart())
async def start_command(
    message: Message,
    state: FSMContext,
    bot_username: str,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    await reset_menu(state)
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[1] == "register" and message.chat.type == ChatType.PRIVATE:
        await start_registration(message, state, bot_username, config, sessionmaker)
        return
    invite_text = ""
    if message.chat.type == ChatType.PRIVATE:
        invite_text = await _maybe_build_invite_text(message, sessionmaker, config)
    await message.answer(
        "Привет! Это бот клана Clash of Clans. Нажмите «Регистрация», чтобы начать."
        f"{invite_text}",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )


async def _get_user_profile(
    sessionmaker: async_sessionmaker,
    telegram_id: int,
) -> models.User | None:
    async with sessionmaker() as session:
        return (
            await session.execute(select(models.User).where(models.User.telegram_id == telegram_id))
        ).scalar_one_or_none()


async def _maybe_build_invite_text(
    message: Message,
    sessionmaker: async_sessionmaker,
    config: BotConfig,
) -> str:
    async with sessionmaker() as session:
        user = (
            await session.execute(
                select(models.User).where(models.User.telegram_id == message.from_user.id)
            )
        ).scalar_one_or_none()
        needs_hint = (
            user is None
            or not user.last_seen_in_main_chat
            or not user.main_chat_member_check_ok
        )
        if not needs_hint:
            return ""
        try:
            member = await message.bot.get_chat_member(
                chat_id=config.main_chat_id,
                user_id=message.from_user.id,
            )
            if member.status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
                return (
                    "\n\nЕсли вы не в чате клана — вступайте сюда: "
                    "https://t.me/+7_RomfG9Dn9mYTVi"
                )
            if user:
                user.last_seen_in_main_chat = datetime.now(timezone.utc)
                user.main_chat_member_check_ok = True
                await session.commit()
            return ""
        except (TelegramBadRequest, TelegramForbiddenError):
            return (
                "\n\nЕсли вы не в чате клана — вступайте сюда: "
                "https://t.me/+7_RomfG9Dn9mYTVi"
            )

@router.message(Command("me"))
async def me_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    await reset_menu(state)
    user = await _get_user_profile(sessionmaker, message.from_user.id)
    logger.debug("profile lookup telegram_id=%s found=%s", message.from_user.id, bool(user))
    if not user:
        await message.answer(
            "Вы ещё не зарегистрированы. Нажмите «Регистрация».",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await message.answer(
        f"Профиль: {user.player_name} ({user.player_tag})\nКлан: {user.clan_tag}",
        reply_markup=profile_menu_reply(),
    )


@router.message(Command("whois"))
async def whois_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    await reset_menu(state)
    target_user = message.reply_to_message.from_user if message.reply_to_message else None
    username = None
    if target_user is None and message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1 and parts[1].startswith("@"):
            username = parts[1].lstrip("@")
    if not target_user and not username:
        await message.answer(
            "Ответьте на сообщение пользователя или укажите @username.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return

    async with sessionmaker() as session:
        if target_user:
            user = (
                await session.execute(
                    select(models.User).where(models.User.telegram_id == target_user.id)
                )
            ).scalar_one_or_none()
        else:
            user = (
                await session.execute(select(models.User).where(models.User.username == username))
            ).scalar_one_or_none()
    if not user:
        await message.answer(
            "Нет данных по этому пользователю.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    label = target_user.full_name if target_user else f"@{username}"
    await message.answer(
        f"{label}: {user.player_name} ({user.player_tag})",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )


@router.message(Command("help"))
async def help_command(
    message: Message,
    state: FSMContext,
    bot_username: str,
    config: BotConfig,
) -> None:
    await reset_state_if_any(state)
    await reset_menu(state)
    await message.answer(
        build_help_text(bot_username),
        parse_mode="HTML",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )


@router.message(Command("rules"))
async def rules_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
) -> None:
    await reset_state_if_any(state)
    await reset_menu(state)
    await message.answer(
        build_rules_text(),
        parse_mode="HTML",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )


@router.message(F.text == "Помощь / Гайд")
async def help_button(
    message: Message,
    state: FSMContext,
    bot_username: str,
    config: BotConfig,
) -> None:
    await reset_state_if_any(state)
    await reset_menu(state)
    await message.answer(
        build_help_text(bot_username),
        parse_mode="HTML",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )


@router.message(
    F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
    F.text.in_(list(MENU_TEXT_ACTIONS.keys())),
)
async def group_menu_router(
    message: Message,
    state: FSMContext,
    bot_username: str,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    action = MENU_TEXT_ACTIONS.get(message.text or "")
    if not action:
        return
    if action == "register":
        await start_registration(message, state, bot_username, config, sessionmaker)
        return
    if action == "profile":
        await me_command(message, state, config, sessionmaker)
        return
    if action == "mystats":
        await mystats_command(message, state, config, sessionmaker, coc_client, bot_username)
        return
    if action == "notify":
        try:
            await send_notify_menu(
                message.bot,
                message.from_user.id,
                message.from_user.id,
                config,
                sessionmaker,
            )
        except TelegramForbiddenError:
            link = build_bot_dm_link(bot_username)
            await message.answer(
                f"Не могу написать вам в ЛС. Напишите боту напрямую: {link}",
                reply_markup=build_bot_dm_keyboard(bot_username, label="Открыть бота"),
            )
            return
        await message.answer(
            "Открыл настройки уведомлений в ЛС.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    if action == "complaint":
        sent = await try_send_dm(
            message.bot,
            message.from_user.id,
            "Чтобы подать жалобу, откройте ЛС и нажмите «📣 Жалоба».",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        if sent:
            await message.answer(
                "Я отправил инструкцию в ЛС. Перейдите туда для жалобы.",
                reply_markup=build_bot_dm_keyboard(bot_username, label="Открыть бота"),
            )
            return
        await message.answer(
            f"Чтобы подать жалобу, откройте ЛС: {build_bot_dm_link(bot_username)}",
            reply_markup=build_bot_dm_keyboard(bot_username, label="Открыть бота"),
        )
        return
    if action == "targets":
        await targets_command(message, state, config, coc_client, sessionmaker)
        return
    if action == "rules":
        await message.answer(
            build_rules_text(),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    if action == "guide":
        await message.answer(
            build_help_text(bot_username),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    if action == "admin":
        if not is_admin(message.from_user.id, config):
            await message.answer(
                "Админ-панель доступна только администраторам.",
                reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
            )
            return
        await set_menu(state, "admin_menu")
        missed_label = await get_missed_attacks_label(coc_client, config.clan_tag)
        await message.answer("Админ-панель.", reply_markup=admin_menu_reply(missed_label))


@router.message(F.text == "📜 Правила клана")
async def rules_button(message: Message, state: FSMContext, config: BotConfig) -> None:
    await rules_command(message, state, config)


@router.message(Command("profile"))
async def profile_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await me_command(message, state, config, sessionmaker)


@router.message(F.text == "Мой профиль")
async def profile_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await me_command(message, state, config, sessionmaker)


@router.message(F.text == "Показать профиль")
async def show_profile_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await me_command(message, state, config, sessionmaker)


@router.message(F.text == "Главное меню")
async def main_menu_button(message: Message, state: FSMContext, config: BotConfig) -> None:
    await reset_state_if_any(state)
    await reset_menu(state)
    await message.answer(
        "Главное меню.",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )


@router.callback_query(F.data.startswith("menu:"))
async def menu_callbacks(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    bot_username: str,
    coc_client: CocClient,
) -> None:
    await callback.answer()
    await reset_state_if_any(state)
    await reset_menu(state)
    if callback.data == "menu:register":
        await start_registration(callback.message, state, bot_username, config, sessionmaker)
    elif callback.data == "menu:me":
        user = await _get_user_profile(sessionmaker, callback.from_user.id)
        logger.debug("profile lookup telegram_id=%s found=%s", callback.from_user.id, bool(user))
        if not user:
            await callback.message.answer(
                "Вы ещё не зарегистрированы. Нажмите «Регистрация».",
                reply_markup=main_menu_reply(is_admin(callback.from_user.id, config)),
            )
            return
        await callback.message.answer(
            f"Профиль: {user.player_name} ({user.player_tag})\nКлан: {user.clan_tag}",
            reply_markup=profile_menu_reply(),
        )
    elif callback.data == "menu:mystats":
        await mystats_command(callback.message, state, config, sessionmaker, coc_client, bot_username)
    elif callback.data == "menu:notify":
        await notify_command(callback.message, state, config, sessionmaker)
    elif callback.data == "menu:targets":
        await targets_command(callback.message, state, config, coc_client, sessionmaker)
    elif callback.data == "menu:rules":
        await callback.message.answer(
            build_rules_text(),
            parse_mode="HTML",
            reply_markup=main_menu_reply(is_admin(callback.from_user.id, config)),
        )
    elif callback.data == "menu:complaint":
        await start_complaint_flow(callback.message, state, config, coc_client)
    elif callback.data == "menu:guide":
        await callback.message.answer(
            build_help_text(bot_username),
            parse_mode="HTML",
            reply_markup=main_menu_reply(is_admin(callback.from_user.id, config)),
        )
    elif callback.data == "menu:admin":
        if not is_admin(callback.from_user.id, config):
            await callback.message.answer(
                "Админ-панель доступна только администраторам.",
                reply_markup=main_menu_reply(is_admin(callback.from_user.id, config)),
            )
            return
        await set_menu(state, "admin_menu")
        missed_label = await get_missed_attacks_label(coc_client, config.clan_tag)
        await callback.message.answer("Админ-панель.", reply_markup=admin_menu_reply(missed_label))


@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def track_main_chat_member(
    message: Message,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    if message.chat.id != config.main_chat_id:
        return
    async with sessionmaker() as session:
        user = (
            await session.execute(select(models.User).where(models.User.telegram_id == message.from_user.id))
        ).scalar_one_or_none()
        if not user:
            return
        user.last_seen_in_main_chat = datetime.now(timezone.utc)
        user.main_chat_member_check_ok = True
        await session.commit()
