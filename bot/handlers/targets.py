from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import targets_menu_reply
from bot.keyboards.targets import targets_select_kb, targets_table_kb
from bot.services.coc_client import CocClient
from bot.utils.state import reset_state_if_any

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("targets"))
async def targets_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    await message.answer(
        "Раздел «Цели на войне». Выберите действие:",
        reply_markup=targets_menu_reply(),
    )


async def _ensure_war_row(
    sessionmaker: async_sessionmaker,
    war: dict,
) -> models.War:
    war_tag = war.get("tag") or war.get("clan", {}).get("tag")
    async with sessionmaker() as session:
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
        return war_row


async def _load_claims(
    sessionmaker: async_sessionmaker,
    war_id: int,
) -> list[models.TargetClaim]:
    async with sessionmaker() as session:
        return (
            await session.execute(
                select(models.TargetClaim).where(models.TargetClaim.war_id == war_id)
            )
        ).scalars().all()


async def _build_targets_table(
    enemies: list[dict],
    claims: list[models.TargetClaim],
    sessionmaker: async_sessionmaker,
) -> tuple[str, bool]:
    claims_map = {claim.enemy_position: claim for claim in claims}
    has_claim = False
    lines = ["*Таблица целей*"]
    async with sessionmaker() as session:
        users = (await session.execute(select(models.User))).scalars().all()
    user_map = {user.telegram_id: user for user in users}
    for enemy in enemies:
        pos = enemy.get("mapPosition")
        name = enemy.get("name") or "?"
        th = enemy.get("townhallLevel")
        base = f"#{pos} {name} TH{th}" if th else f"#{pos} {name}"
        claim = claims_map.get(pos)
        if claim:
            has_claim = True
            user = user_map.get(claim.claimed_by_telegram_id)
            holder = user.username or user.player_name if user else "участник"
            lines.append(f"{base} — занято: {holder}")
        else:
            lines.append(f"{base} — свободно")
    lines.append("")
    lines.append("_Флажки в игре API не предоставляет._")
    return "\n".join(lines), has_claim


@router.message(F.text == "Цели на войне")
async def targets_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    await targets_command(message, state, config, coc_client, sessionmaker)


@router.message(F.text == "Выбрать цель")
async def targets_select_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    try:
        war = await coc_client.get_current_war(config.clan_tag)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch war: %s", exc)
        await message.answer("Не удалось получить войну.", reply_markup=targets_menu_reply())
        return
    if war.get("state") != "preparation":
        await message.answer(
            "Выбор целей доступен только в подготовке.",
            reply_markup=targets_menu_reply(),
        )
        return
    enemies = war.get("opponent", {}).get("members", [])
    if not enemies:
        await message.answer("Нет списка противников.", reply_markup=targets_menu_reply())
        return
    war_row = await _ensure_war_row(sessionmaker, war)
    claims = await _load_claims(sessionmaker, war_row.id)
    taken_positions = {claim.enemy_position for claim in claims}
    await message.answer(
        "Выберите свободную цель:",
        reply_markup=targets_select_kb(enemies, taken_positions),
    )


@router.message(F.text == "Таблица целей")
async def targets_table_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    try:
        war = await coc_client.get_current_war(config.clan_tag)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch war: %s", exc)
        await message.answer("Не удалось получить войну.", reply_markup=targets_menu_reply())
        return
    enemies = war.get("opponent", {}).get("members", [])
    if not enemies:
        await message.answer("Нет списка противников.", reply_markup=targets_menu_reply())
        return
    war_row = await _ensure_war_row(sessionmaker, war)
    claims = await _load_claims(sessionmaker, war_row.id)
    table_text, has_claim = await _build_targets_table(enemies, claims, sessionmaker)
    await message.answer(
        table_text,
        parse_mode="Markdown",
        reply_markup=targets_table_kb(has_claim),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("targets:claim:"))
async def target_claim(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    await callback.answer("Проверяю…")
    await reset_state_if_any(state)
    position = int(callback.data.split(":")[2])
    try:
        war = await coc_client.get_current_war(config.clan_tag)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch war: %s", exc)
        await callback.message.answer("Не удалось получить войну.", reply_markup=targets_menu_reply())
        return
    if war.get("state") != "preparation":
        await callback.message.answer(
            "Выбор целей доступен только в подготовке.",
            reply_markup=targets_menu_reply(),
        )
        return
    war_row = await _ensure_war_row(sessionmaker, war)
    async with sessionmaker() as session:
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
            existing = (
                await session.execute(
                    select(models.TargetClaim).where(
                        models.TargetClaim.war_id == war_row.id,
                        models.TargetClaim.enemy_position == position,
                    )
                )
            ).scalar_one_or_none()
            holder = "другой участник"
            if existing:
                user = (
                    await session.execute(
                        select(models.User).where(
                            models.User.telegram_id == existing.claimed_by_telegram_id
                        )
                    )
                ).scalar_one_or_none()
                if user:
                    holder = user.username or user.player_name
            await callback.message.answer(
                f"Цель уже занята: {holder}. Выберите другую цель.",
                reply_markup=targets_menu_reply(),
            )
            return
    await callback.message.answer(
        f"Вы заняли цель #{position}.",
        reply_markup=targets_menu_reply(),
    )


@router.callback_query(lambda c: c.data == "targets:refresh")
async def targets_refresh(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    await callback.answer("Обновляю…")
    await reset_state_if_any(state)
    try:
        war = await coc_client.get_current_war(config.clan_tag)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch war: %s", exc)
        await callback.message.answer("Не удалось получить войну.", reply_markup=targets_menu_reply())
        return
    enemies = war.get("opponent", {}).get("members", [])
    if not enemies:
        await callback.message.answer("Нет списка противников.", reply_markup=targets_menu_reply())
        return
    war_row = await _ensure_war_row(sessionmaker, war)
    claims = await _load_claims(sessionmaker, war_row.id)
    table_text, has_claim = await _build_targets_table(enemies, claims, sessionmaker)
    await callback.message.answer(
        table_text,
        parse_mode="Markdown",
        reply_markup=targets_table_kb(has_claim),
    )


@router.callback_query(lambda c: c.data == "targets:unclaim")
async def targets_unclaim(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    await callback.answer("Снимаю…")
    await reset_state_if_any(state)
    try:
        war = await coc_client.get_current_war(config.clan_tag)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch war: %s", exc)
        await callback.message.answer("Не удалось получить войну.", reply_markup=targets_menu_reply())
        return
    war_row = await _ensure_war_row(sessionmaker, war)
    async with sessionmaker() as session:
        claims = (
            await session.execute(
                select(models.TargetClaim).where(
                    models.TargetClaim.war_id == war_row.id,
                    models.TargetClaim.claimed_by_telegram_id == callback.from_user.id,
                )
            )
        ).scalars().all()
        if not claims:
            await callback.message.answer(
                "У вас нет закреплённых целей.",
                reply_markup=targets_menu_reply(),
            )
            return
        for claim in claims:
            await session.delete(claim)
        await session.commit()
    await callback.message.answer(
        "Ваша цель освобождена.",
        reply_markup=targets_menu_reply(),
    )
