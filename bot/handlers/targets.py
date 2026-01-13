from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import main_menu_reply
from bot.keyboards.targets import targets_kb
from bot.services.coc_client import CocClient
from bot.services.permissions import is_admin

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("targets"))
async def targets_command(
    message: Message,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    try:
        war = await coc_client.get_current_war(config.clan_tag)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch war: %s", exc)
        await message.answer("Не удалось получить войну.", reply_markup=main_menu_reply())
        return

    if war.get("state") != "preparation":
        await message.answer("Выбор целей доступен только в подготовке.", reply_markup=main_menu_reply())
        return

    enemies = war.get("opponent", {}).get("members", [])
    if not enemies:
        await message.answer("Нет списка противников.", reply_markup=main_menu_reply())
        return

    async with sessionmaker() as session:
        war_tag = war.get("tag") or war.get("clan", {}).get("tag")
        existing = None
        if war_tag:
            existing = (
                await session.execute(select(models.War).where(models.War.war_tag == war_tag))
            ).scalar_one_or_none()
        if existing is None:
            existing = models.War(
                war_tag=war_tag,
                war_type=war.get("warType", "unknown"),
                state=war.get("state", "unknown"),
                opponent_name=war.get("opponent", {}).get("name"),
                opponent_tag=war.get("opponent", {}).get("tag"),
            )
            session.add(existing)
            await session.commit()

    await message.answer("Выберите цель:", reply_markup=targets_kb(enemies))


@router.callback_query(lambda c: c.data and c.data.startswith("target:"))
async def target_claim(
    callback: CallbackQuery,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    position = int(callback.data.split(":", 1)[1])

    try:
        war = await coc_client.get_current_war(config.clan_tag)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch war: %s", exc)
        await callback.message.answer("Не удалось получить войну.", reply_markup=main_menu_reply())
        await callback.answer()
        return

    if war.get("state") != "preparation":
        await callback.message.answer("Выбор целей доступен только в подготовке.", reply_markup=main_menu_reply())
        await callback.answer()
        return

    async with sessionmaker() as session:
        war_tag = war.get("tag") or war.get("clan", {}).get("tag")
        war_row = (
            await session.execute(select(models.War).where(models.War.war_tag == war_tag))
        ).scalar_one_or_none()
        if war_row is None:
            war_row = models.War(
                war_tag=war_tag,
                war_type=war.get("warType", "unknown"),
                state=war.get("state", "unknown"),
                opponent_name=war.get("opponent", {}).get("name"),
                opponent_tag=war.get("opponent", {}).get("tag"),
            )
            session.add(war_row)
            await session.commit()

        try:
            async with session.begin():
                session.add(
                    models.TargetClaim(
                        war_id=war_row.id,
                        enemy_position=position,
                        claimed_by_telegram_id=callback.from_user.id,
                    )
                )
        except IntegrityError:
            await callback.message.answer("Цель уже занята.", reply_markup=main_menu_reply())
            await callback.answer()
            return

    await callback.message.answer(
        f"Цель #{position} закреплена за вами.",
        reply_markup=main_menu_reply(),
    )
    await callback.answer()


@router.message(Command("unclaim"))
async def unclaim_command(
    message: Message,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Укажите номер цели: /unclaim 5", reply_markup=main_menu_reply())
        return
    position = int(parts[1])
    async with sessionmaker() as session:
        claim = (
            await session.execute(
                select(models.TargetClaim).where(models.TargetClaim.enemy_position == position)
            )
        ).scalar_one_or_none()
        if not claim:
            await message.answer("Эта цель не занята.", reply_markup=main_menu_reply())
            return
        if claim.claimed_by_telegram_id != message.from_user.id and not is_admin(
            message.from_user.id, config
        ):
            await message.answer("Вы не можете снять чужую цель.", reply_markup=main_menu_reply())
            return
        await session.delete(claim)
        await session.commit()
    await message.answer("Цель освобождена.", reply_markup=main_menu_reply())
