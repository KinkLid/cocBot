from __future__ import annotations

from datetime import time

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.db import models
from bot.keyboards.notify import notify_channel_kb

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
async def notify_command(message: Message, sessionmaker: async_sessionmaker) -> None:
    if message.text and len(message.text.split(maxsplit=1)) > 1:
        times_raw = message.text.split(maxsplit=1)[1]
        try:
            times = _parse_times(times_raw)
        except ValueError:
            await message.answer("Формат времени: /notify 09:00 или /notify 09:00,18:00")
            return
        async with sessionmaker() as session:
            user = (
                await session.execute(
                    select(models.User).where(models.User.telegram_id == message.from_user.id)
                )
            ).scalar_one_or_none()
            if not user:
                await message.answer("Сначала зарегистрируйтесь /register")
                return
            prefs = dict(user.notify_pref or {})
            prefs["times"] = times
            user.notify_pref = prefs
            await session.commit()
        await message.answer("Время уведомлений сохранено.")
        return

    await message.answer("Куда отправлять уведомления?", reply_markup=notify_channel_kb())


@router.callback_query(lambda c: c.data and c.data.startswith("notify:"))
async def notify_callback(callback: CallbackQuery, sessionmaker: async_sessionmaker) -> None:
    channel = callback.data.split(":", 1)[1]
    async with sessionmaker() as session:
        user = (
            await session.execute(
                select(models.User).where(models.User.telegram_id == callback.from_user.id)
            )
        ).scalar_one_or_none()
        if not user:
            await callback.message.answer("Сначала зарегистрируйтесь /register")
            await callback.answer()
            return
        prefs = dict(user.notify_pref or {})
        prefs["channel"] = channel
        user.notify_pref = prefs
        await session.commit()
    await callback.message.answer("Настройки уведомлений сохранены.")
    await callback.answer()
