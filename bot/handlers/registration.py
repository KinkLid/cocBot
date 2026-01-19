from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import main_menu_reply, registration_reply
from bot.keyboards.hints import hint_ack_kb
from bot.services.coc_client import CocClient
from bot.services.permissions import is_admin
from bot.texts.hints import REGISTER_HINT
from bot.utils.navigation import reset_menu
from bot.utils.state import reset_state_if_any
from bot.utils.tokens import hash_token
from bot.utils.validators import is_valid_tag, normalize_tag
from bot.utils.telegram import build_bot_dm_keyboard, build_bot_dm_link, try_send_dm

logger = logging.getLogger(__name__)
router = Router()


class RegisterState(StatesGroup):
    waiting_tag = State()
    waiting_token = State()


async def _ensure_private(message: Message, bot_username: str) -> bool:
    if message.chat.type == ChatType.PRIVATE:
        return True
    link = build_bot_dm_link(bot_username, start_param="register")
    sent = await try_send_dm(
        message.bot,
        message.from_user.id,
        (
            "Регистрация доступна только в ЛС. "
            "Нажмите кнопку ниже, чтобы начать."
        ),
        reply_markup=build_bot_dm_keyboard(bot_username, label="Начать регистрацию", start_param="register"),
    )
    if sent:
        await message.answer(
            "Я отправил вам инструкцию в ЛС. Перейдите туда для регистрации.",
            reply_markup=build_bot_dm_keyboard(bot_username, label="Открыть бота", start_param="register"),
        )
        return False
    await message.answer(
        f"Регистрация доступна только в ЛС. Перейдите: {link}",
        reply_markup=build_bot_dm_keyboard(bot_username, label="Открыть бота", start_param="register"),
    )
    return False


async def _reject_if_registered(
    message: Message,
    sessionmaker: async_sessionmaker,
    config: BotConfig,
) -> bool:
    async with sessionmaker() as session:
        existing = (
            await session.execute(select(models.User).where(models.User.telegram_id == message.from_user.id))
        ).scalar_one_or_none()
    if not existing:
        return False
    await message.answer(
        f"Вы уже зарегистрированы как {existing.player_name} ({existing.player_tag}).",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )
    await message.answer(
        "Повторная регистрация запрещена. Нажмите «Показать профиль» или «Главное меню».",
        reply_markup=registration_reply(),
    )
    return True


async def start_registration(
    message: Message,
    state: FSMContext,
    bot_username: str,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    if await _reject_if_registered(message, sessionmaker, config):
        return
    if not await _ensure_private(message, bot_username):
        return
    await state.clear()
    await state.set_state(RegisterState.waiting_tag)
    await message.answer(REGISTER_HINT, parse_mode=ParseMode.HTML, reply_markup=hint_ack_kb())
    await message.answer(
        "Введите ваш player tag (например #ABC123):",
        reply_markup=registration_reply(),
    )


@router.message(Command("register"))
async def register_command(
    message: Message,
    state: FSMContext,
    bot_username: str,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await start_registration(message, state, bot_username, config, sessionmaker)


@router.message(F.text == "Регистрация")
async def register_button(
    message: Message,
    state: FSMContext,
    bot_username: str,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await start_registration(message, state, bot_username, config, sessionmaker)


@router.message(RegisterState.waiting_tag)
async def register_tag(message: Message, state: FSMContext, config: BotConfig) -> None:
    if message.text == "Главное меню":
        await state.clear()
        await reset_menu(state)
        await message.answer(
            "Главное меню.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    tag = normalize_tag(message.text or "")
    if not is_valid_tag(tag):
        await message.answer(
            "Некорректный тег. Пример: #ABC123",
            reply_markup=registration_reply(),
        )
        return
    await state.update_data(player_tag=tag)
    await state.set_state(RegisterState.waiting_token)
    await message.answer(
        "Теперь пришлите API token из игры:",
        reply_markup=registration_reply(),
    )


@router.message(RegisterState.waiting_token)
async def register_token(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    if message.text == "Главное меню":
        await state.clear()
        await reset_menu(state)
        await message.answer(
            "Главное меню.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    token = (message.text or "").strip()
    data = await state.get_data()
    player_tag = data.get("player_tag")
    if not player_tag:
        await state.clear()
        await message.answer(
            "Что-то пошло не так. Нажмите «Регистрация» ещё раз.",
            reply_markup=registration_reply(),
        )
        return

    try:
        verified = await coc_client.verify_token(player_tag, token)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Verify token failed: %s", exc)
        await message.answer(
            "Не удалось проверить токен. Попробуйте позже.",
            reply_markup=registration_reply(),
        )
        return

    if not verified:
        await message.answer(
            "Токен не подходит. Проверьте правильность.",
            reply_markup=registration_reply(),
        )
        return

    try:
        player_data = await coc_client.get_player(player_tag)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Fetch player failed: %s", exc)
        await message.answer(
            "Не удалось получить профиль игрока.",
            reply_markup=registration_reply(),
        )
        return

    clan_tag = player_data.get("clan", {}).get("tag")
    if not clan_tag or clan_tag.upper() != config.clan_tag.upper():
        await message.answer(
            "Игрок не состоит в этом клане.",
            reply_markup=registration_reply(),
        )
        return
    token_hash = hash_token(token, config.token_salt)

    async with sessionmaker() as session:
        existing = (
            await session.execute(select(models.User).where(models.User.telegram_id == message.from_user.id))
        ).scalar_one_or_none()

        if existing:
            existing.player_tag = player_tag
            existing.player_name = player_data.get("name", existing.player_name)
            existing.clan_tag = clan_tag
            existing.username = message.from_user.username
            existing.last_clan_check_at = datetime.now(timezone.utc)
            existing.is_in_clan_cached = True
            existing.token_hash = token_hash
            if existing.first_seen_in_clan_at is None:
                existing.first_seen_in_clan_at = datetime.now(timezone.utc)
        else:
            session.add(
                models.User(
                    telegram_id=message.from_user.id,
                    username=message.from_user.username,
                    player_tag=player_tag,
                    player_name=player_data.get("name", ""),
                    clan_tag=clan_tag,
                    token_hash=token_hash,
                    last_clan_check_at=datetime.now(timezone.utc),
                    is_in_clan_cached=True,
                    first_seen_in_clan_at=datetime.now(timezone.utc),
                    notify_pref={
                        "dm_enabled": False,
                        "dm_categories": {
                            "war": False,
                            "cwl": False,
                            "capital": False,
                        },
                        "dm_window": "always",
                    },
                )
            )
        await session.commit()

    await state.clear()
    await message.answer(
        "Регистрация завершена. Спасибо!",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )
