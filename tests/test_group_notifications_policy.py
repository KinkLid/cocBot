from __future__ import annotations

import asyncio

from bot.config import BotConfig
from bot.services.notifications import NotificationService


class DummyBot:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, chat_id: int, text: str, parse_mode=None, **kwargs) -> None:  # noqa: ANN001
        self.sent.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode, "kwargs": kwargs})


def make_config() -> BotConfig:
    return BotConfig(
        bot_token="token",
        coc_api_token="coc",
        clan_tag="#CLAN",
        main_chat_id=-100,
        admin_chat_id=None,
        admin_telegram_ids={1},
        timezone="UTC",
        database_url="sqlite+aiosqlite:///tmp/test.db",
        token_salt="salt",
    )


def test_only_monthly_summary_is_sent_to_main_chat(monkeypatch) -> None:
    bot = DummyBot()
    service = NotificationService(bot, make_config(), sessionmaker=object(), coc_client=object())

    async def _enabled(_notify_type: str) -> bool:
        return True

    monkeypatch.setattr(service, "_chat_type_enabled", _enabled)

    asyncio.run(service._send_chat_notification("monthly", "monthly_summary"))
    asyncio.run(service._send_chat_notification("war", "war_start"))

    assert [m["text"] for m in bot.sent] == ["monthly"]
    assert bot.sent[0]["chat_id"] == -100
