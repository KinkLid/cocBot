from __future__ import annotations

from aiogram.enums import ParseMode
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.db import models
from bot.keyboards.hints import hint_ack_kb


async def send_hint_once(
    message: Message,
    sessionmaker: async_sessionmaker,
    user_id: int,
    field_name: str,
    text: str,
) -> bool:
    async with sessionmaker() as session:
        user = (
            await session.execute(select(models.User).where(models.User.telegram_id == user_id))
        ).scalar_one_or_none()
        if not user:
            return False
        if getattr(user, field_name, False):
            return False
        await message.answer(text, reply_markup=hint_ack_kb(), parse_mode=ParseMode.HTML)
        setattr(user, field_name, True)
        await session.commit()
        return True
