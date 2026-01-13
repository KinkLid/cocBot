from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from bot.config import BotConfig

logger = logging.getLogger(__name__)


async def notify_user(bot: Bot, config: BotConfig, user_id: int, text: str, pref: dict[str, Any]) -> None:
    channel = pref.get("channel", config.default_notify_channel)
    if channel == "chat":
        await bot.send_message(chat_id=config.main_chat_id, text=text)
        return
    try:
        await bot.send_message(chat_id=user_id, text=text)
    except TelegramForbiddenError:
        logger.info("DM forbidden for %s", user_id)
        await bot.send_message(
            chat_id=config.main_chat_id,
            text="Не могу отправить ЛС. Откройте ЛС или переключитесь на уведомления в чате.",
        )
