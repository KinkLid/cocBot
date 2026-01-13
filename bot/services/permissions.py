from __future__ import annotations

from bot.config import BotConfig


def is_admin(telegram_id: int, config: BotConfig) -> bool:
    return telegram_id in config.admin_telegram_ids
