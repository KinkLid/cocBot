from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import admin_action_reply, admin_menu_reply, main_menu_reply
from bot.services.permissions import is_admin
from bot.utils.state import reset_state_if_any

logger = logging.getLogger(__name__)
router = Router()


class AdminState(StatesGroup):
    waiting_wipe_target = State()


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
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await state.set_state(AdminState.waiting_wipe_target)
    await message.answer(
        "Пришлите тег игрока или ответьте на сообщение пользователя.",
        reply_markup=admin_action_reply(),
    )


@router.message(F.text == "Админ-панель")
async def admin_panel_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await message.answer("Админ-панель.", reply_markup=admin_menu_reply())


@router.message(F.text == "Очистить игрока")
async def wipe_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await state.set_state(AdminState.waiting_wipe_target)
    await message.answer(
        "Пришлите тег игрока или ответьте на сообщение пользователя.",
        reply_markup=admin_action_reply(),
    )


@router.message(F.text == "Диагностика")
async def diagnostics_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    async with sessionmaker() as session:
        users_count = (await session.execute(select(models.User))).scalars().all()
        wars_count = (await session.execute(select(models.War))).scalars().all()
    await message.answer(
        f"Диагностика: пользователей {len(users_count)}, войн {len(wars_count)}.",
        reply_markup=admin_menu_reply(),
    )


@router.message(F.text == "Назад")
async def admin_back(message: Message, state: FSMContext, config: BotConfig) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Главное меню.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await message.answer("Админ-панель.", reply_markup=admin_menu_reply())


@router.message(AdminState.waiting_wipe_target)
async def wipe_target(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return

    target_user = message.reply_to_message.from_user if message.reply_to_message else None
    target_text = (message.text or "").strip()

    async with sessionmaker() as session:
        if target_user:
            user = (
                await session.execute(
                    select(models.User).where(models.User.telegram_id == target_user.id)
                )
            ).scalar_one_or_none()
        elif target_text.startswith("@"):
            user = (
                await session.execute(
                    select(models.User).where(models.User.username == target_text.lstrip("@"))
                )
            ).scalar_one_or_none()
        else:
            user = (
                await session.execute(select(models.User).where(models.User.player_tag == target_text))
            ).scalar_one_or_none()

        if not user:
            await message.answer(
                "Пользователь не найден. Попробуйте ещё раз или нажмите «Назад».",
                reply_markup=admin_action_reply(),
            )
            return

        await session.execute(
            delete(models.TargetClaim).where(models.TargetClaim.claimed_by_telegram_id == user.telegram_id)
        )
        await session.execute(
            delete(models.WarParticipation).where(models.WarParticipation.telegram_id == user.telegram_id)
        )
        await session.execute(
            delete(models.CapitalContribution).where(models.CapitalContribution.telegram_id == user.telegram_id)
        )
        await session.execute(
            delete(models.StatsDaily).where(models.StatsDaily.telegram_id == user.telegram_id)
        )
        await session.delete(user)
        await session.commit()

    await state.clear()
    await message.answer(
        "Данные пользователя удалены.",
        reply_markup=admin_menu_reply(),
    )
