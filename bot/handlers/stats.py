from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import main_menu_reply
from bot.keyboards.seasons import seasons_kb
from bot.services.permissions import is_admin
from bot.utils.state import reset_state_if_any

router = Router()


@router.message(Command("mystats"))
async def mystats_command(
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
            "Вы не зарегистрированы.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await message.answer(
        "Статистика доступна: войны, звезды, участие в рейдах. Периоды: всё время/сезон.",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )


@router.message(Command("stats"))
async def stats_command(message: Message, state: FSMContext, config: BotConfig) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Недостаточно прав.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await message.answer(
        "Админская статистика: используйте @username или player_tag.",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )


@router.message(Command("season"))
async def season_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    async with sessionmaker() as session:
        seasons = (
            await session.execute(select(models.Season.id, models.Season.name).order_by(models.Season.end_at.desc()))
        ).all()
    if not seasons:
        await message.answer(
            "Сезоны ещё не сформированы.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await message.answer("Выберите сезон:", reply_markup=seasons_kb(seasons))


@router.callback_query(lambda c: c.data and c.data.startswith("season:"))
async def season_callback(callback: CallbackQuery, config: BotConfig) -> None:
    season_id = int(callback.data.split(":", 1)[1])
    await callback.message.answer(
        f"Сезон выбран: {season_id}. Используйте /mystats для просмотра.",
        reply_markup=main_menu_reply(is_admin(callback.from_user.id, config)),
    )
    await callback.answer()


@router.message(F.text == "Моя статистика")
async def mystats_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await mystats_command(message, state, config, sessionmaker)
