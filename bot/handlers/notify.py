from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import main_menu_reply, notify_menu_reply
from bot.services.permissions import is_admin
from bot.utils.state import reset_state_if_any

router = Router()


@router.message(Command("notify"))
async def notify_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    async with sessionmaker() as session:
        user = (
            await session.execute(select(models.User).where(models.User.telegram_id == message.from_user.id))
        ).scalar_one_or_none()
        if not user:
            await message.answer(
                "Вы ещё не зарегистрированы. Нажмите «Регистрация».",
                reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
            )
            return
        prefs = dict(user.notify_pref or {})
        dm_enabled = bool(prefs.get("dm_enabled", False))
    await message.answer(
        f"Уведомления в общий чат приходят всегда. ЛС: {'✅ включены' if dm_enabled else '⛔ выключены'}.",
        reply_markup=notify_menu_reply(dm_enabled),
    )


@router.message(F.text == "Настройки уведомлений")
async def notify_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await notify_command(message, state, config, sessionmaker)


@router.message(F.text.in_({"Включить ЛС", "Выключить ЛС"}))
async def notify_toggle_dm_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    async with sessionmaker() as session:
        user = (
            await session.execute(
                select(models.User).where(models.User.telegram_id == message.from_user.id)
            )
        ).scalar_one_or_none()
        if not user:
            await message.answer(
                "Вы ещё не зарегистрированы. Нажмите «Регистрация».",
                reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
            )
            return
        prefs = dict(user.notify_pref or {})
        dm_enabled = bool(prefs.get("dm_enabled", False))
        new_state = not dm_enabled if message.text == "Включить ЛС" else False
        if dm_enabled and message.text == "Выключить ЛС":
            new_state = False
        elif not dm_enabled and message.text == "Включить ЛС":
            new_state = True
        elif dm_enabled and message.text == "Включить ЛС":
            await message.answer("ЛС уже включены.", reply_markup=notify_menu_reply(dm_enabled))
            return
        elif not dm_enabled and message.text == "Выключить ЛС":
            await message.answer("ЛС уже выключены.", reply_markup=notify_menu_reply(dm_enabled))
            return
        prefs["dm_enabled"] = new_state
        user.notify_pref = prefs
        await session.commit()
    if new_state:
        try:
            await message.bot.send_message(
                chat_id=message.from_user.id,
                text="Проверка: уведомления будут приходить в ЛС.",
            )
        except TelegramForbiddenError:
            prefs = dict(prefs)
            prefs["dm_enabled"] = False
            async with sessionmaker() as session:
                user = (
                    await session.execute(
                        select(models.User).where(models.User.telegram_id == message.from_user.id)
                    )
                ).scalar_one_or_none()
                if user:
                    user.notify_pref = prefs
                    await session.commit()
            await message.answer(
                "Не могу писать в ЛС. Откройте ЛС и включите снова.",
                reply_markup=notify_menu_reply(False),
            )
            return
        await message.answer(
            "Готово! ЛС включены.",
            reply_markup=notify_menu_reply(True),
        )
        return
    await message.answer(
        "Готово! ЛС выключены.",
        reply_markup=notify_menu_reply(False),
    )


@router.message(F.text.in_({"✅ ЛС включены", "⛔ ЛС выключены"}))
async def notify_status_button(message: Message) -> None:
    await message.answer("Состояние уже выбрано.")
