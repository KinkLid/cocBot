from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.handlers.notify import notify_command
from bot.handlers.registration import start_registration
from bot.handlers.stats import mystats_command
from bot.handlers.targets import targets_command
from bot.keyboards.common import admin_menu_reply, main_menu_reply, profile_menu_reply
from bot.services.coc_client import CocClient
from bot.services.permissions import is_admin
from bot.texts.help import build_help_text
from bot.utils.navigation import reset_menu, set_menu
from bot.utils.state import reset_state_if_any

router = Router()
logger = logging.getLogger(__name__)


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
    await message.answer(
        "Привет! Это бот клана Clash of Clans. Нажмите «Регистрация», чтобы начать.",
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
        parse_mode="Markdown",
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
        parse_mode="Markdown",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )


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
        await mystats_command(callback.message, state, config, sessionmaker, coc_client)
    elif callback.data == "menu:notify":
        await notify_command(callback.message, state, config, sessionmaker)
    elif callback.data == "menu:targets":
        await targets_command(callback.message, state, config, coc_client, sessionmaker)
    elif callback.data == "menu:guide":
        await callback.message.answer(
            build_help_text(bot_username),
            parse_mode="Markdown",
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
        await callback.message.answer("Админ-панель.", reply_markup=admin_menu_reply())
