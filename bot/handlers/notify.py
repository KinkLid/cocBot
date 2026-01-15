from __future__ import annotations

from datetime import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import main_menu_reply, notify_menu_reply
from bot.services.permissions import is_admin
from bot.utils.state import reset_state_if_any

router = Router()


def _parse_times(raw: str) -> list[str]:
    times: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        hh, mm = part.split(":", 1)
        parsed = time(int(hh), int(mm))
        times.append(parsed.strftime("%H:%M"))
    return times


@router.message(Command("notify"))
async def notify_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    if message.text and len(message.text.split(maxsplit=1)) > 1:
        times_raw = message.text.split(maxsplit=1)[1]
        try:
            times = _parse_times(times_raw)
        except ValueError:
            await message.answer(
                "Формат времени: 09:00 или 09:00,18:00.",
                reply_markup=notify_menu_reply(),
            )
            return
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
            prefs["times"] = times
            user.notify_pref = prefs
            await session.commit()
        await message.answer(
            "Время уведомлений сохранено.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return

    await message.answer(
        "Выберите, куда отправлять уведомления:",
        reply_markup=notify_menu_reply(),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("notify:"))
async def notify_callback(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    channel = callback.data.split(":", 1)[1]
    async with sessionmaker() as session:
        user = (
            await session.execute(
                select(models.User).where(models.User.telegram_id == callback.from_user.id)
            )
        ).scalar_one_or_none()
        if not user:
            await callback.message.answer(
                "Вы ещё не зарегистрированы. Нажмите «Регистрация».",
                reply_markup=main_menu_reply(is_admin(callback.from_user.id, config)),
            )
            await callback.answer()
            return
        prefs = dict(user.notify_pref or {})
        prefs["channel"] = channel
        user.notify_pref = prefs
        await session.commit()
    if channel == "dm":
        try:
            await callback.bot.send_message(
                chat_id=callback.from_user.id,
                text="Проверка: уведомления будут приходить в ЛС.",
            )
        except TelegramForbiddenError:
            await callback.message.answer(
                "Не могу писать в ЛС. Откройте ЛС и выберите «В ЛС» снова, "
                "или используйте уведомления в общем чате.",
                reply_markup=notify_menu_reply(),
            )
            await callback.answer()
            return
    await callback.message.answer(
        "Готово! Настройки уведомлений сохранены.",
        reply_markup=notify_menu_reply(),
    )
    await callback.answer()


@router.message(F.text == "Настройки уведомлений")
async def notify_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await notify_command(message, state, config, sessionmaker)


@router.message(F.text == "В ЛС")
async def notify_dm_button(
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
        prefs["channel"] = "dm"
        user.notify_pref = prefs
        await session.commit()
    try:
        await message.bot.send_message(
            chat_id=message.from_user.id,
            text="Проверка: уведомления будут приходить в ЛС.",
        )
    except TelegramForbiddenError:
        await message.answer(
            "Не могу писать в ЛС. Откройте ЛС и выберите «В ЛС» снова, "
            "или используйте уведомления в общем чате.",
            reply_markup=notify_menu_reply(),
        )
        return
    await message.answer(
        "Готово! Уведомления будут приходить в ЛС.",
        reply_markup=notify_menu_reply(),
    )


@router.message(F.text == "В общий чат")
async def notify_chat_button(
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
        prefs["channel"] = "chat"
        user.notify_pref = prefs
        await session.commit()
    await message.answer(
        "Готово! Уведомления будут приходить в общий чат.",
        reply_markup=notify_menu_reply(),
    )
