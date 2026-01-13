from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.services.permissions import is_admin

router = Router()


@router.message(Command("wipe"))
async def wipe_command(message: Message, config: BotConfig, sessionmaker: async_sessionmaker) -> None:
    if not is_admin(message.from_user.id, config):
        await message.answer("Недостаточно прав.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Укажите @username или player_tag.")
        return
    target = parts[1]

    async with sessionmaker() as session:
        if target.startswith("@"):
            user = (
                await session.execute(
                    select(models.User).where(models.User.username == target.lstrip("@"))
                )
            ).scalar_one_or_none()
        else:
            user = (
                await session.execute(select(models.User).where(models.User.player_tag == target))
            ).scalar_one_or_none()
        if not user:
            await message.answer("Пользователь не найден.")
            return
        await session.execute(delete(models.TargetClaim).where(models.TargetClaim.claimed_by_telegram_id == user.telegram_id))
        await session.execute(delete(models.WarParticipation).where(models.WarParticipation.telegram_id == user.telegram_id))
        await session.execute(delete(models.CapitalContribution).where(models.CapitalContribution.telegram_id == user.telegram_id))
        await session.execute(delete(models.StatsDaily).where(models.StatsDaily.telegram_id == user.telegram_id))
        await session.delete(user)
        await session.commit()
    await message.answer("Данные пользователя удалены.")
