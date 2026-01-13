from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import main_menu_reply
from bot.services.permissions import is_admin
from bot.utils.state import reset_state_if_any

router = Router()


@router.message(Command("wipe"))
async def wipe_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Недостаточно прав.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Укажите @username или player_tag.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
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
            await message.answer(
                "Пользователь не найден.",
                reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
            )
            return
        await session.execute(delete(models.TargetClaim).where(models.TargetClaim.claimed_by_telegram_id == user.telegram_id))
        await session.execute(delete(models.WarParticipation).where(models.WarParticipation.telegram_id == user.telegram_id))
        await session.execute(delete(models.CapitalContribution).where(models.CapitalContribution.telegram_id == user.telegram_id))
        await session.execute(delete(models.StatsDaily).where(models.StatsDaily.telegram_id == user.telegram_id))
        await session.delete(user)
        await session.commit()
    await message.answer(
        "Данные пользователя удалены.",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )


@router.message(F.text == "Админ-панель")
async def admin_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Недостаточно прав.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await message.answer(
        "Используйте /wipe @username или /wipe #TAG для очистки данных.",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )
