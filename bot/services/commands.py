from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeAllChatAdministrators
from aiogram.types import BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats
from aiogram.types import BotCommandScopeDefault

logger = logging.getLogger(__name__)


def _base_commands() -> list[BotCommand]:
    return [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="help", description="Гайд и справка"),
        BotCommand(command="rules", description="Правила клана"),
        BotCommand(command="register", description="Регистрация в боте"),
        BotCommand(command="profile", description="Мой профиль"),
        BotCommand(command="stats", description="Моя статистика"),
        BotCommand(command="targets", description="Цели на войне"),
        BotCommand(command="complaint", description="Подать жалобу"),
    ]


def _private_commands() -> list[BotCommand]:
    return [
        *_base_commands(),
        BotCommand(command="notify", description="Настройки уведомлений"),
    ]


def _group_commands() -> list[BotCommand]:
    return _base_commands()


def _admin_commands() -> list[BotCommand]:
    return [
        *_group_commands(),
        BotCommand(command="admin", description="Админ-панель"),
        BotCommand(command="users", description="Список зарегистрированных"),
        BotCommand(command="complaints", description="Список жалоб"),
        BotCommand(command="missed", description="Кто не атаковал сейчас"),
        BotCommand(command="set_chat_notify", description="Настройки уведомлений чата"),
        BotCommand(command="update_commands", description="Обновить список команд"),
    ]


async def register_bot_commands(bot: Bot) -> None:
    logger.info("Registering bot command menu scopes")
    await bot.set_my_commands(
        _private_commands(),
        scope=BotCommandScopeAllPrivateChats(),
        language_code="ru",
    )
    await bot.set_my_commands(
        _group_commands(),
        scope=BotCommandScopeAllGroupChats(),
        language_code="ru",
    )
    await bot.set_my_commands(
        _admin_commands(),
        scope=BotCommandScopeAllChatAdministrators(),
        language_code="ru",
    )
    await bot.set_my_commands(
        _private_commands(),
        scope=BotCommandScopeDefault(),
        language_code="ru",
    )
