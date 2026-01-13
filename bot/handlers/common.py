from __future__ import annotations

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.db import models
from bot.handlers.registration import start_register_flow
from bot.keyboards.common import main_menu

router = Router()


@router.message(CommandStart())
async def start_command(message: Message, state: FSMContext) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[1] == "register" and message.chat.type == ChatType.PRIVATE:
        await start_register_flow(message, state)
        return
    await message.answer(
        "Привет! Это бот клана Clash of Clans. Используйте /register для регистрации.",
        reply_markup=main_menu(),
    )


@router.message(Command("me"))
async def me_command(message: Message, sessionmaker: async_sessionmaker) -> None:
    async with sessionmaker() as session:
        user = (
            await session.execute(select(models.User).where(models.User.telegram_id == message.from_user.id))
        ).scalar_one_or_none()
    if not user:
        await message.answer("Вы не зарегистрированы. Используйте /register.")
        return
    await message.answer(f"Вы связаны с {user.player_name} ({user.player_tag})")


@router.message(Command("whois"))
async def whois_command(message: Message, sessionmaker: async_sessionmaker) -> None:
    target_user = message.reply_to_message.from_user if message.reply_to_message else None
    username = None
    if target_user is None and message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1 and parts[1].startswith("@"):
            username = parts[1].lstrip("@")
    if not target_user and not username:
        await message.answer("Ответьте на сообщение пользователя или укажите @username.")
        return

    async with sessionmaker() as session:
        if target_user:
            user = (
                await session.execute(
                    select(models.User).where(models.User.telegram_id == target_user.id)
                )
            ).scalar_one_or_none()
        else:
            user = (
                await session.execute(select(models.User).where(models.User.username == username))
            ).scalar_one_or_none()
    if not user:
        await message.answer("Нет данных по этому пользователю.")
        return
    label = target_user.full_name if target_user else f"@{username}"
    await message.answer(f"{label}: {user.player_name} ({user.player_tag})")


@router.callback_query()
async def menu_callbacks(
    callback: CallbackQuery,
    state: FSMContext,
    sessionmaker: async_sessionmaker,
) -> None:
    if callback.data == "menu:register":
        await start_register_flow(callback.message, state)
    elif callback.data == "menu:me":
        await me_command(callback.message, sessionmaker)
    elif callback.data == "menu:mystats":
        await callback.message.answer("Используйте /mystats для статистики.")
    elif callback.data == "menu:notify":
        await callback.message.answer("Используйте /notify для уведомлений.")
    await callback.answer()
