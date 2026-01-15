from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import targets_admin_reply, targets_menu_reply
from bot.keyboards.targets import targets_select_kb
from bot.services.permissions import is_admin
from bot.services.coc_client import CocClient
from bot.utils.state import reset_state_if_any

logger = logging.getLogger(__name__)
router = Router()


class TargetsState(StatesGroup):
    waiting_external_name = State()


def _menu_reply(config: BotConfig, telegram_id: int):
    return targets_admin_reply() if is_admin(telegram_id, config) else targets_menu_reply()


async def _load_war(coc_client: CocClient, clan_tag: str) -> dict | None:
    try:
        return await coc_client.get_current_war(clan_tag)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch war: %s", exc)
        return None


async def _ensure_war_row(sessionmaker: async_sessionmaker, war: dict) -> models.War:
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


async def _load_claims(sessionmaker: async_sessionmaker, war_id: int) -> list[models.TargetClaim]:
    async with sessionmaker() as session:
        return (
            await session.execute(select(models.TargetClaim).where(models.TargetClaim.war_id == war_id))
        ).scalars().all()


async def _build_table(
    enemies: list[dict],
    claims: list[models.TargetClaim],
    sessionmaker: async_sessionmaker,
) -> str:
    claims_map = {claim.enemy_position: claim for claim in claims}
    async with sessionmaker() as session:
        users = (await session.execute(select(models.User))).scalars().all()
    user_map = {user.telegram_id: user for user in users}

    lines = ["*Таблица целей*"]
    for enemy in enemies:
        pos = enemy.get("mapPosition")
        name = enemy.get("name") or "?"
        th = enemy.get("townhallLevel")
        base = f"#{pos} {name} TH{th}" if th else f"#{pos} {name}"
        claim = claims_map.get(pos)
        if not claim:
            lines.append(f"{base} — свободно")
            continue
        if claim.external_player_name:
            holder = claim.external_player_name
        elif claim.claimed_by_telegram_id:
            user = user_map.get(claim.claimed_by_telegram_id)
            if user:
                tg_name = f"@{user.username}" if user.username else user.player_name
                holder = f"{tg_name} / {user.player_name}"
            else:
                holder = "участник"
        else:
            holder = "участник"
        lines.append(f"{base} — занято: {holder}")
    lines.append("")
    lines.append("_Флажки в игре API не предоставляет._")
    return "\n".join(lines)


async def _show_selection(
    message: Message,
    war: dict,
    war_row: models.War,
    sessionmaker: async_sessionmaker,
    user_id: int,
    admin_mode: bool,
) -> None:
    enemies = war.get("opponent", {}).get("members", [])
    claims = await _load_claims(sessionmaker, war_row.id)
    taken = {claim.enemy_position for claim in claims if claim.claimed_by_telegram_id != user_id}
    my_claims = {claim.enemy_position for claim in claims if claim.claimed_by_telegram_id == user_id}
    admin_rows: list[tuple[str, str]] = []
    if admin_mode:
        for claim in claims:
            if claim.claimed_by_telegram_id == user_id:
                continue
            label = f"🔧 #{claim.enemy_position}"
            if claim.external_player_name:
                label = f"🔧 #{claim.enemy_position} {claim.external_player_name}"
            admin_rows.append((label, f"targets:admin-unclaim:{claim.enemy_position}"))
    await message.answer(
        "Выберите противника:",
        reply_markup=targets_select_kb(enemies, taken, my_claims, admin_rows=admin_rows),
    )


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
        "Раздел «Цели на войне».",
        reply_markup=_menu_reply(config, message.from_user.id),
    )


@router.message(F.text == "Цели на войне")
async def targets_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    await targets_command(message, state, config, coc_client, sessionmaker)


@router.message(F.text == "Выбрать противника")
async def targets_select_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    war = await _load_war(coc_client, config.clan_tag)
    if not war:
        await message.answer("Не удалось получить войну.", reply_markup=_menu_reply(config, message.from_user.id))
        return
    if war.get("state") != "preparation":
        await message.answer(
            "Выбор целей доступен только в подготовке.",
            reply_markup=_menu_reply(config, message.from_user.id),
        )
        return
    enemies = war.get("opponent", {}).get("members", [])
    if not enemies:
        await message.answer("Нет списка противников.", reply_markup=_menu_reply(config, message.from_user.id))
        return
    war_row = await _ensure_war_row(sessionmaker, war)
    await _show_selection(
        message,
        war,
        war_row,
        sessionmaker,
        message.from_user.id,
        is_admin(message.from_user.id, config),
    )


@router.message(F.text.in_({"Таблица целей", "Обновить таблицу"}))
async def targets_table_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    war = await _load_war(coc_client, config.clan_tag)
    if not war:
        await message.answer("Не удалось получить войну.", reply_markup=_menu_reply(config, message.from_user.id))
        return
    enemies = war.get("opponent", {}).get("members", [])
    if not enemies:
        await message.answer("Нет списка противников.", reply_markup=_menu_reply(config, message.from_user.id))
        return
    war_row = await _ensure_war_row(sessionmaker, war)
    claims = await _load_claims(sessionmaker, war_row.id)
    table_text = await _build_table(enemies, claims, sessionmaker)
    await message.answer(
        table_text,
        parse_mode="Markdown",
        reply_markup=_menu_reply(config, message.from_user.id),
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
    war = await _load_war(coc_client, config.clan_tag)
    if not war:
        await callback.message.answer("Не удалось получить войну.")
        return
    if war.get("state") != "preparation":
        await callback.message.answer("Выбор целей доступен только в подготовке.")
        return
    war_row = await _ensure_war_row(sessionmaker, war)

    async with sessionmaker() as session:
        my_claims = (
            await session.execute(
                select(models.TargetClaim).where(
                    models.TargetClaim.war_id == war_row.id,
                    models.TargetClaim.claimed_by_telegram_id == callback.from_user.id,
                )
            )
        ).scalars().all()
        if len(my_claims) >= 2:
            await callback.message.answer("Можно выбрать не более двух целей.")
            await callback.message.delete()
            return
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
            await callback.message.answer("Цель уже занята. Выберите другую.")
            await callback.message.delete()
            return

    await callback.message.delete()
    await callback.message.answer(f"Вы заняли цель #{position}.")


@router.callback_query(lambda c: c.data and c.data.startswith("targets:toggle:"))
async def target_toggle(
    callback: CallbackQuery,
    state: FSMContext,
    sessionmaker: async_sessionmaker,
) -> None:
    await callback.answer("Обновляю…")
    await reset_state_if_any(state)
    position = int(callback.data.split(":")[2])
    async with sessionmaker() as session:
        claim = (
            await session.execute(
                select(models.TargetClaim).where(
                    models.TargetClaim.enemy_position == position,
                    models.TargetClaim.claimed_by_telegram_id == callback.from_user.id,
                )
            )
        ).scalar_one_or_none()
        if not claim:
            await callback.message.answer("Эта цель недоступна.")
            await callback.message.delete()
            return
        await session.delete(claim)
        await session.commit()
    await callback.message.delete()
    await callback.message.answer(f"Цель #{position} освобождена.")


@router.callback_query(lambda c: c.data and c.data.startswith("targets:admin-unclaim:"))
async def target_admin_unclaim(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await callback.answer("Снимаю…")
    await reset_state_if_any(state)
    if not is_admin(callback.from_user.id, config):
        await callback.message.answer("Доступно только администраторам.")
        return
    position = int(callback.data.split(":")[2])
    async with sessionmaker() as session:
        claim = (
            await session.execute(
                select(models.TargetClaim).where(models.TargetClaim.enemy_position == position)
            )
        ).scalar_one_or_none()
        if not claim:
            await callback.message.answer("Цель уже свободна.")
            await callback.message.delete()
            return
        await session.delete(claim)
        await session.commit()
    await callback.message.delete()
    await callback.message.answer(f"Назначение для цели #{position} снято.")


@router.message(F.text == "Назначить другому")
async def targets_assign_other(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer("Доступно только администраторам.")
        return
    war = await _load_war(coc_client, config.clan_tag)
    if not war:
        await message.answer("Не удалось получить войну.", reply_markup=_menu_reply(config, message.from_user.id))
        return
    if war.get("state") != "preparation":
        await message.answer(
            "Выбор целей доступен только в подготовке.",
            reply_markup=_menu_reply(config, message.from_user.id),
        )
        return
    enemies = war.get("opponent", {}).get("members", [])
    if not enemies:
        await message.answer("Нет списка противников.", reply_markup=_menu_reply(config, message.from_user.id))
        return
    war_row = await _ensure_war_row(sessionmaker, war)
    claims = await _load_claims(sessionmaker, war_row.id)
    taken = {claim.enemy_position for claim in claims}
    await message.answer(
        "Выберите свободную цель для назначения:",
        reply_markup=targets_select_kb(enemies, taken, set(), assign_mode=True),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("targets:assign:"))
async def targets_assign_select(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer("Введите ник игрока…")
    position = int(callback.data.split(":")[2])
    await state.update_data(assign_position=position)
    await state.set_state(TargetsState.waiting_external_name)
    await callback.message.delete()
    await callback.message.answer("Введите ник игрока в игре:")


@router.message(TargetsState.waiting_external_name)
async def targets_assign_name(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    data = await state.get_data()
    position = data.get("assign_position")
    if not position:
        await state.clear()
        await message.answer("Не удалось определить цель. Повторите.")
        return
    name = (message.text or "").strip()
    if not name:
        await message.answer("Введите ник игрока.")
        return
    war = await _load_war(coc_client, config.clan_tag)
    if not war:
        await state.clear()
        await message.answer("Не удалось получить войну.", reply_markup=_menu_reply(config, message.from_user.id))
        return
    war_row = await _ensure_war_row(sessionmaker, war)
    async with sessionmaker() as session:
        try:
            async with session.begin():
                session.add(
                    models.TargetClaim(
                        war_id=war_row.id,
                        enemy_position=position,
                        claimed_by_telegram_id=None,
                        external_player_name=name,
                    )
                )
        except IntegrityError:
            await message.answer("Цель уже занята. Выберите другую.")
            await state.clear()
            return
    await state.clear()
    await message.answer(
        f"Назначено: цель #{position} за {name}.",
        reply_markup=_menu_reply(config, message.from_user.id),
    )
