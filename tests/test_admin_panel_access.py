from __future__ import annotations

import asyncio
from types import SimpleNamespace

from bot.config import BotConfig
from bot.handlers import admin as admin_handlers
from bot.services.guards import ClanAccessMiddleware
from bot.ui.labels import label


class DummyMessage:
    def __init__(self, user_id: int, text: str, chat_type: str = "private") -> None:
        self.from_user = SimpleNamespace(id=user_id)
        self.text = text
        self.chat = SimpleNamespace(type=chat_type)
        self.answers: list[dict] = []

    async def answer(self, text: str, reply_markup=None, **kwargs) -> None:  # noqa: ANN001
        self.answers.append({"text": text, "reply_markup": reply_markup, "kwargs": kwargs})


class DummyState:
    pass


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


def test_admin_button_opens_panel_in_private(monkeypatch) -> None:
    message = DummyMessage(user_id=42, text=label("admin"), chat_type="private")
    config = make_config(admin_ids={42})

    async def _noop(*args, **kwargs):  # noqa: ANN002, ANN003
        return None

    monkeypatch.setattr(admin_handlers, "reset_state_if_any", _noop)
    monkeypatch.setattr(admin_handlers, "reset_menu", _noop)
    monkeypatch.setattr(admin_handlers, "set_menu", _noop)
    monkeypatch.setattr(admin_handlers, "get_missed_attacks_label", _noop)

    asyncio.run(admin_handlers.admin_panel_button(message, DummyState(), config, coc_client=object()))

    assert message.answers[-1]["text"] == "Админ-панель."


def test_non_admin_button_gets_denied(monkeypatch) -> None:
    message = DummyMessage(user_id=7, text=label("admin"), chat_type="private")
    config = make_config(admin_ids={42})

    async def _noop(*args, **kwargs):  # noqa: ANN002, ANN003
        return None

    monkeypatch.setattr(admin_handlers, "reset_state_if_any", _noop)

    asyncio.run(admin_handlers.admin_panel_button(message, DummyState(), config, coc_client=object()))

    assert message.answers[-1]["text"].startswith("Админ-панель доступна только")


def test_admin_button_in_group_follows_same_rules(monkeypatch) -> None:
    message = DummyMessage(user_id=42, text=label("admin"), chat_type="group")
    config = make_config(admin_ids={42})

    async def _noop(*args, **kwargs):  # noqa: ANN002, ANN003
        return None

    monkeypatch.setattr(admin_handlers, "reset_state_if_any", _noop)
    monkeypatch.setattr(admin_handlers, "reset_menu", _noop)
    monkeypatch.setattr(admin_handlers, "set_menu", _noop)
    monkeypatch.setattr(admin_handlers, "get_missed_attacks_label", _noop)

    asyncio.run(admin_handlers.admin_panel_button(message, DummyState(), config, coc_client=object()))

    assert message.answers[-1]["text"] == "Админ-панель."


def test_middleware_does_not_touch_db_for_admin(monkeypatch) -> None:
    config = make_config(admin_ids={42})
    middleware = ClanAccessMiddleware(config, sessionmaker=object(), coc_client=object())
    message = DummyMessage(user_id=42, text=label("admin"))

    async def _broken(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("ORM mapping exploded")

    monkeypatch.setattr("bot.services.guards.ensure_registered_and_in_clan", _broken)
    async def _never_exempt(event, state_value):  # noqa: ANN001, ANN002
        return False

    monkeypatch.setattr("bot.services.guards._is_exempt", _never_exempt)

    called = {"handler": False}

    async def handler(event, data):  # noqa: ANN001, ANN002
        called["handler"] = True
        return "ok"

    result = asyncio.run(middleware(handler, message, data={}))

    assert result == "ok"
    assert called["handler"] is True
