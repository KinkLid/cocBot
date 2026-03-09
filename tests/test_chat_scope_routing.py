from __future__ import annotations

import asyncio
from types import SimpleNamespace

from bot.config import BotConfig
from bot.services.guards import ClanAccessMiddleware


class DummyBot:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, chat_id: int, text: str, reply_markup=None, **kwargs) -> None:  # noqa: ANN001
        self.sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup, "kwargs": kwargs})


class DummyMessage:
    def __init__(self, user_id: int, text: str, chat_type: str, bot: DummyBot | None = None) -> None:
        self.from_user = SimpleNamespace(id=user_id)
        self.text = text
        self.entities = []
        self.chat = SimpleNamespace(type=chat_type)
        self.bot = bot or DummyBot()
        self.answers: list[dict] = []

    async def answer(self, text: str, reply_markup=None, **kwargs) -> None:  # noqa: ANN001
        self.answers.append({"text": text, "reply_markup": reply_markup, "kwargs": kwargs})


class DummyCallback:
    def __init__(self, user_id: int, data: str, chat_type: str) -> None:
        self.from_user = SimpleNamespace(id=user_id)
        self.data = data
        self.message = DummyMessage(user_id=user_id, text="", chat_type=chat_type)
        self.answers: list[str] = []

    async def answer(self, text: str | None = None) -> None:
        self.answers.append(text or "")


def make_config(*, admin_ids: set[int]) -> BotConfig:
    return BotConfig(
        bot_token="token",
        coc_api_token="coc",
        clan_tag="#CLAN",
        main_chat_id=-100,
        admin_chat_id=None,
        admin_telegram_ids=admin_ids,
        timezone="UTC",
        database_url="sqlite+aiosqlite:///tmp/test.db",
        token_salt="salt",
    )


def test_group_message_from_regular_user_is_ignored() -> None:
    middleware = ClanAccessMiddleware(make_config(admin_ids=set()), sessionmaker=object(), coc_client=object())
    message = DummyMessage(user_id=11, text="hello", chat_type="group")
    called = {"handler": False}

    async def handler(event, data):  # noqa: ANN001, ANN002
        called["handler"] = True

    asyncio.run(middleware(handler, message, data={"bot_username": "bot"}))

    assert called["handler"] is False
    assert message.answers == []


def test_group_command_from_regular_user_is_ignored() -> None:
    middleware = ClanAccessMiddleware(make_config(admin_ids=set()), sessionmaker=object(), coc_client=object())
    message = DummyMessage(user_id=11, text="/start", chat_type="group")
    called = {"handler": False}

    async def handler(event, data):  # noqa: ANN001, ANN002
        called["handler"] = True

    asyncio.run(middleware(handler, message, data={"bot_username": "bot"}))

    assert called["handler"] is False
    assert message.answers == []


def test_group_callback_is_ignored() -> None:
    middleware = ClanAccessMiddleware(make_config(admin_ids={42}), sessionmaker=object(), coc_client=object())
    callback = DummyCallback(user_id=42, data="menu:me", chat_type="group")
    called = {"handler": False}

    async def handler(event, data):  # noqa: ANN001, ANN002
        called["handler"] = True

    asyncio.run(middleware(handler, callback, data={"bot_username": "bot"}))

    assert called["handler"] is False
    assert callback.message.answers == []


def test_group_command_from_admin_is_redirected_to_dm() -> None:
    middleware = ClanAccessMiddleware(make_config(admin_ids={42}), sessionmaker=object(), coc_client=object())
    bot = DummyBot()
    message = DummyMessage(user_id=42, text="/admin", chat_type="group", bot=bot)
    called = {"handler": False}

    async def handler(event, data):  # noqa: ANN001, ANN002
        called["handler"] = True

    asyncio.run(middleware(handler, message, data={"bot_username": "coc_bot"}))

    assert called["handler"] is False
    assert message.answers == []
    assert len(bot.sent) == 1
    assert bot.sent[0]["chat_id"] == 42
    assert "t.me/coc_bot" in bot.sent[0]["text"]


def test_private_command_keeps_normal_flow(monkeypatch) -> None:
    middleware = ClanAccessMiddleware(make_config(admin_ids=set()), sessionmaker=object(), coc_client=object())
    message = DummyMessage(user_id=99, text="/start", chat_type="private")

    async def _always_exempt(event, state_value):  # noqa: ANN001, ANN002
        return True

    monkeypatch.setattr("bot.services.guards._is_exempt", _always_exempt)

    called = {"handler": False}

    async def handler(event, data):  # noqa: ANN001, ANN002
        called["handler"] = True
        return "ok"

    result = asyncio.run(middleware(handler, message, data={"bot_username": "bot"}))

    assert result == "ok"
    assert called["handler"] is True
