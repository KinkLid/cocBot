from __future__ import annotations

from bot.config import BotConfig

MAIN_CHAT_INVITE_LINK = "https://t.me/+7_RomfG9Dn9mYTVi"


def build_main_chat_invite_text(config: BotConfig) -> str:
    return f"Если вы не в чате клана — вступайте сюда: {MAIN_CHAT_INVITE_LINK}"
