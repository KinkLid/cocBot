from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import BaseMiddleware
from aiogram.enums import MessageEntityType
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import main_menu_reply
from bot.services.coc_client import CocClient
from bot.services.permissions import is_admin
from bot.ui.labels import all_label_variants, label, label_variants

logger = logging.getLogger(__name__)

CLAN_CHECK_TTL = timedelta(minutes=10)


async def ensure_registered_and_in_clan(
    telegram_id: int,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
    ttl: timedelta = CLAN_CHECK_TTL,
) -> tuple[models.User | None, bool]:
    async with sessionmaker() as session:
        user = (
            await session.execute(select(models.User).where(models.User.telegram_id == telegram_id))
        ).scalar_one_or_none()
        if not user:
            return None, False
        now = datetime.now(timezone.utc)
        if user.last_clan_check_at and user.is_in_clan_cached is not None:
            last_check = user.last_clan_check_at
            if last_check.tzinfo is None:
                last_check = last_check.replace(tzinfo=timezone.utc)
            if now - last_check <= ttl:
                return user, bool(user.is_in_clan_cached)
        try:
            player_data = await coc_client.get_player(user.player_tag)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to refresh clan membership for %s: %s", telegram_id, exc)
            if user.is_in_clan_cached is not None:
                return user, bool(user.is_in_clan_cached)
            return user, False
        clan_tag = player_data.get("clan", {}).get("tag")
        in_clan = bool(clan_tag and clan_tag.upper() == config.clan_tag.upper())
        user.is_in_clan_cached = in_clan
        user.last_clan_check_at = now
        if clan_tag:
            user.clan_tag = clan_tag
        if in_clan and user.first_seen_in_clan_at is None:
            user.first_seen_in_clan_at = now
        await session.commit()
        return user, in_clan


def _state_is_registration(state_value: str | None) -> bool:
    if not state_value:
        return False
    return state_value.startswith("RegisterState")


def _state_is_complaint(state_value: str | None) -> bool:
    if not state_value:
        return False
    return state_value.startswith("ComplaintState")


async def _is_exempt(event: Message | CallbackQuery, state_value: str | None) -> bool:
    if _state_is_registration(state_value):
        return True
    if isinstance(event, Message):
        text = (event.text or "").strip()
        if text.startswith(("/start", "/help", "/register")):
            return True
        if text in (
            label_variants("register")
            | label_variants("guide")
            | label_variants("rules")
            | label_variants("main_menu")
        ):
            return True
        return False
    data = event.data or ""
    return data in {"menu:register", "menu:guide", "menu:rules", "hint:ok"}


async def _is_blacklist_exempt(event: Message | CallbackQuery, state_value: str | None) -> bool:
    if _state_is_complaint(state_value):
        return True
    if isinstance(event, Message):
        text = (event.text or "").strip()
        if text.startswith(("/help", "/rules", "/complaint")):
            return True
        if text in (
            label_variants("complaint")
            | label_variants("guide")
            | label_variants("rules")
            | label_variants("main_menu")
        ):
            return True
        return False
    data = event.data or ""
    if data.startswith("complaint:"):
        return True
    return data in {"menu:complaint", "menu:guide", "menu:rules", "complaint:cancel"}


async def _is_whitelisted_player(
    sessionmaker: async_sessionmaker,
    player_tag: str | None,
) -> bool:
    if not player_tag:
        return False
    async with sessionmaker() as session:
        row = (
            await session.execute(
                select(models.WhitelistPlayer)
                .where(models.WhitelistPlayer.player_tag == player_tag)
                .where(models.WhitelistPlayer.is_active.is_(True))
            )
        ).scalar_one_or_none()
        return row is not None


async def _is_blacklisted_player(
    sessionmaker: async_sessionmaker,
    player_tag: str,
) -> bool:
    async with sessionmaker() as session:
        row = (
            await session.execute(
                select(models.BlacklistPlayer)
                .where(models.BlacklistPlayer.player_tag == player_tag)
                .where(models.BlacklistPlayer.is_active.is_(True))
            )
        ).scalar_one_or_none()
        return row is not None


async def _deny_access(
    event: Message | CallbackQuery,
    config: BotConfig,
    telegram_id: int,
    text: str,
    *,
    is_registered: bool,
) -> None:
    reply_markup = main_menu_reply(is_admin(telegram_id, config), is_registered=is_registered)
    if isinstance(event, CallbackQuery):
        await event.answer(text)
        if event.message:
            await event.message.answer(text, reply_markup=reply_markup)
        return
    await event.answer(text, reply_markup=reply_markup)


def _is_command_message(message: Message) -> bool:
    if not message.text:
        return False
    if message.text.startswith("/"):
        return True
    if not message.entities:
        return False
    for entity in message.entities:
        if entity.type == MessageEntityType.BOT_COMMAND and entity.offset == 0:
            return True
    return False


def _is_menu_or_label_message(message: Message) -> bool:
    if not message.text:
        return False
    return message.text in all_label_variants()


class ClanAccessMiddleware(BaseMiddleware):
    def __init__(
        self,
        config: BotConfig,
        sessionmaker: async_sessionmaker,
        coc_client: CocClient,
        ttl: timedelta = CLAN_CHECK_TTL,
    ) -> None:
        self._config = config
        self._sessionmaker = sessionmaker
        self._coc_client = coc_client
        self._ttl = ttl

    async def __call__(self, handler, event: Message | CallbackQuery, data: dict):
        state = data.get("state")
        state_value = await state.get_state() if state else None
        if isinstance(event, Message):
            if not _is_command_message(event) and not _is_menu_or_label_message(event):
                return await handler(event, data)
        if await _is_exempt(event, state_value):
            return await handler(event, data)
        telegram_id = event.from_user.id if event.from_user else None
        if telegram_id is None:
            return await handler(event, data)
        user, in_clan = await ensure_registered_and_in_clan(
            telegram_id,
            self._config,
            self._sessionmaker,
            self._coc_client,
            ttl=self._ttl,
        )
        if not user:
            logger.info("Access denied: not registered (telegram_id=%s)", telegram_id)
            await _deny_access(
                event,
                self._config,
                telegram_id,
                f"Сначала зарегистрируйтесь: {label('register')}",
                is_registered=False,
            )
            return None
        if not is_admin(telegram_id, self._config):
            whitelisted = await _is_whitelisted_player(self._sessionmaker, user.player_tag)
            if not whitelisted:
                blacklisted = await _is_blacklisted_player(self._sessionmaker, user.player_tag)
                if blacklisted and not await _is_blacklist_exempt(event, state_value):
                    logger.info("Access denied: blacklisted (telegram_id=%s player_tag=%s)", telegram_id, user.player_tag)
                    await _deny_access(
                        event,
                        self._config,
                        telegram_id,
                        "Ваш доступ ограничен. Свяжитесь с админами.",
                        is_registered=True,
                    )
                    return None
        if not in_clan:
            logger.info(
                "Access denied: not in clan (telegram_id=%s player_tag=%s)",
                telegram_id,
                user.player_tag,
            )
            await _deny_access(
                event,
                self._config,
                telegram_id,
                "Вы не состоите в нашем клане. Доступ ограничен.",
                is_registered=True,
            )
            return None
        return await handler(event, data)
