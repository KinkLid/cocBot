from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import targets_admin_reply, targets_menu_reply
from bot.keyboards.targets import build_targets_keyboard, targets_admin_action_kb, targets_admin_members_kb
from bot.services.permissions import is_admin
from bot.services.coc_client import CocClient
from bot.services.hints import send_hint_once
from bot.texts.hints import TARGETS_HINT
from bot.ui.labels import admin_unclaim_label, label, label_variants
from bot.ui.renderers import render_targets_table, short_name
from bot.utils.navigation import reset_menu
from bot.utils.notification_events import build_war_event_key
from bot.utils.state import reset_state_if_any
from bot.utils.validators import normalize_tag
from bot.utils.war_rules import get_war_start_time, is_rules_window_active

logger = logging.getLogger(__name__)
router = Router()


def _menu_reply(config: BotConfig, telegram_id: int):
    return targets_admin_reply() if is_admin(telegram_id, config) else targets_menu_reply()


def _sorted_enemies(enemies: list[dict]) -> list[dict]:
    return sorted(enemies, key=lambda enemy: enemy.get("mapPosition") or 0)


def _sorted_members(members: list[dict]) -> list[dict]:
    return sorted(members, key=lambda member: member.get("mapPosition") or 0)


async def _load_war(coc_client: CocClient, clan_tag: str) -> dict | None:
    try:
        return await coc_client.get_current_war(clan_tag)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch war: %s", exc)
        return None


def _is_active_war_state(state: str | None) -> bool:
    return state in {"preparation", "inWar"}


def _resolve_war_event(war: dict, clan_tag: str) -> tuple[str, str | None]:
    war_type = (war.get("warType") or "").lower()
    event_type = "cwl_war" if war_type == "cwl" else "war"
    event_key = build_war_event_key(war, clan_tag)
    return event_type, event_key


def _normalize_member_tag(tag: str | None) -> str | None:
    if not tag:
        return None
    return normalize_tag(tag)


def _is_user_in_war(user: models.User, war: dict) -> bool:
    user_tag = _normalize_member_tag(user.player_tag)
    if not user_tag:
        return False
    members = war.get("clan", {}).get("members", [])
    member_tags = {
        _normalize_member_tag(member.get("tag"))
        for member in members
        if member.get("tag")
    }
    return user_tag in member_tags


def _resolve_member_position(war: dict, player_tag: str | None) -> int | None:
    normalized_tag = _normalize_member_tag(player_tag)
    if not normalized_tag:
        return None
    members = war.get("clan", {}).get("members", [])
    for member in members:
        member_tag = _normalize_member_tag(member.get("tag"))
        if member_tag == normalized_tag:
            return member.get("mapPosition")
    return None


def _is_position_limit_active(war: dict) -> bool:
    start_time = get_war_start_time(war)
    return is_rules_window_active(start_time)


def _format_reserved_label(name: str | None, tag: str | None) -> str | None:
    return name or tag


async def _resolve_claim_holder_label(
    sessionmaker: async_sessionmaker,
    claim: models.TargetClaim,
) -> str | None:
    reserved_label = _format_reserved_label(
        claim.reserved_for_player_name,
        claim.reserved_for_player_tag,
    )
    if reserved_label:
        return reserved_label
    if not claim.claimed_by_user_id:
        return None
    async with sessionmaker() as session:
        user = (
            await session.execute(
                select(models.User).where(models.User.telegram_id == claim.claimed_by_user_id)
            )
        ).scalar_one_or_none()
    if not user:
        return None
    return f"@{user.username}" if user.username else user.player_name


def _find_member_by_tag(war: dict, tag: str) -> dict | None:
    normalized_tag = _normalize_member_tag(tag)
    if not normalized_tag:
        return None
    members = war.get("clan", {}).get("members", [])
    for member in members:
        if _normalize_member_tag(member.get("tag")) == normalized_tag:
            return member
    return None


def _is_target_position_allowed(war: dict, user: models.User, target_position: int) -> bool:
    if not _is_position_limit_active(war):
        return True
    member_position = _resolve_member_position(war, user.player_tag)
    if not member_position:
        return True
    return target_position <= member_position + 10


async def _safe_delete_message(message: Message, notify_text: str | None = None) -> bool:
    try:
        await message.delete()
        return True
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        logger.warning("Failed to delete message: %s", exc)
        if notify_text:
            await message.answer(notify_text)
        return False
    except TelegramAPIError as exc:
        logger.exception("Telegram API error on delete: %s", exc)
        if notify_text:
            await message.answer(notify_text)
        return False


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


async def _load_claims(
    sessionmaker: async_sessionmaker,
    event_type: str,
    event_key: str | None,
) -> list[models.TargetClaim]:
    if not event_key:
        logger.warning("Targets claim load skipped: missing event_key (event_type=%s)", event_type)
        return []
    async with sessionmaker() as session:
        return (
            await session.execute(
                select(models.TargetClaim)
                .where(models.TargetClaim.event_type == event_type)
                .where(models.TargetClaim.event_key == event_key)
            )
        ).scalars().all()


async def _load_user(sessionmaker: async_sessionmaker, telegram_id: int) -> models.User | None:
    async with sessionmaker() as session:
        return (
            await session.execute(select(models.User).where(models.User.telegram_id == telegram_id))
        ).scalar_one_or_none()


async def _build_table_messages(
    enemies: list[dict],
    claims: list[models.TargetClaim],
    sessionmaker: async_sessionmaker,
) -> list[str]:
    async with sessionmaker() as session:
        users = (await session.execute(select(models.User))).scalars().all()
    user_map = {user.telegram_id: user for user in users}
    claims_map = {claim.enemy_position: claim for claim in claims}
    rows: list[dict[str, str | int | None]] = []
    for enemy in _sorted_enemies(enemies):
        pos = enemy.get("mapPosition")
        claim = claims_map.get(pos)
        holder = None
        status = "free"
        if claim:
            status = "taken"
            reserved_label = _format_reserved_label(
                claim.reserved_for_player_name,
                claim.reserved_for_player_tag,
            )
            if reserved_label:
                holder = reserved_label
            elif claim.claimed_by_user_id:
                user = user_map.get(claim.claimed_by_user_id)
                if user:
                    holder = f"@{user.username}" if user.username else user.player_name
                else:
                    holder = "участник"
            else:
                holder = "участник"
        rows.append(
            {
                "position": pos,
                "name": enemy.get("name"),
                "townhall": enemy.get("townhallLevel"),
                "status": status,
                "holder": holder,
            }
        )
    return render_targets_table(
        rows,
        hint=f"Нажмите «{label('targets_select')}», чтобы забронировать цель.",
    )


async def _build_admin_targets_markup(
    war: dict,
    sessionmaker: async_sessionmaker,
    event_type: str,
    event_key: str | None,
) -> InlineKeyboardMarkup:
    enemies = _sorted_enemies(war.get("opponent", {}).get("members", []))
    claims = await _load_claims(sessionmaker, event_type, event_key)
    taken = {claim.enemy_position for claim in claims}
    admin_assigned = {claim.enemy_position for claim in claims if claim.reserved_by_admin_id}
    return build_targets_keyboard(
        enemies,
        mode="admin",
        taken_positions=taken,
        my_positions=set(),
        admin_assigned_positions=admin_assigned,
    )


async def _send_admin_targets_list(
    message: Message | None,
    callback: CallbackQuery | None,
    war: dict,
    sessionmaker: async_sessionmaker,
    event_type: str,
    event_key: str | None,
    text: str = "Выберите цель для назначения:",
) -> None:
    markup = await _build_admin_targets_markup(war, sessionmaker, event_type, event_key)
    if callback and callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=markup)
            return
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            logger.warning("Failed to edit admin targets list: %s", exc)
    if message:
        await message.answer(text, reply_markup=markup)
    elif callback and callback.message:
        await callback.message.answer(text, reply_markup=markup)


async def _show_admin_target_details(
    callback: CallbackQuery,
    war: dict,
    sessionmaker: async_sessionmaker,
    event_type: str,
    event_key: str | None,
    position: int,
) -> None:
    enemies = {enemy.get("mapPosition"): enemy for enemy in war.get("opponent", {}).get("members", [])}
    enemy = enemies.get(position, {})
    th = enemy.get("townhallLevel")
    name = enemy.get("name")
    claim = None
    claims = await _load_claims(sessionmaker, event_type, event_key)
    for entry in claims:
        if entry.enemy_position == position:
            claim = entry
            break
    lines = [f"Выбрана цель #{position}" + (f" TH{th}" if th else "")]
    if name:
        lines.append(f"Противник: {short_name(name)}")
    if claim:
        holder = await _resolve_claim_holder_label(sessionmaker, claim)
        if holder:
            lines.append(f"Сейчас занято: {holder}")
        else:
            lines.append("Сейчас занято: участник")
    else:
        lines.append("Цель свободна.")
    markup = targets_admin_action_kb(position, has_claim=claim is not None)
    if callback.message:
        await callback.message.edit_text("\n".join(lines), reply_markup=markup)


async def _admin_release_claim(
    sessionmaker: async_sessionmaker,
    event_type: str,
    event_key: str | None,
    enemy_position: int,
    admin_id: int,
) -> bool:
    if not event_key:
        return False
    try:
        async with sessionmaker() as session:
            claim = (
                await session.execute(
                    select(models.TargetClaim).where(
                        models.TargetClaim.event_type == event_type,
                        models.TargetClaim.event_key == event_key,
                        models.TargetClaim.enemy_position == enemy_position,
                    )
                )
            ).scalar_one_or_none()
            if not claim:
                return False
            owner = _format_reserved_label(
                claim.reserved_for_player_name,
                claim.reserved_for_player_tag,
            ) or (str(claim.claimed_by_user_id) if claim.claimed_by_user_id else None)
            await session.delete(claim)
            await session.commit()
        logger.info(
            "Admin released claim (admin_id=%s enemy_position=%s event_key=%s old_owner=%s)",
            admin_id,
            enemy_position,
            event_key,
            owner,
        )
        return True
    except SQLAlchemyError as exc:
        logger.exception(
            "Failed to release claim (admin_id=%s enemy_position=%s event_key=%s): %s",
            admin_id,
            enemy_position,
            event_key,
            exc,
        )
        return False


async def _assign_target_to_member(
    sessionmaker: async_sessionmaker,
    war_row: models.War,
    event_type: str,
    event_key: str | None,
    enemy_position: int,
    member: dict,
    admin_id: int,
) -> None:
    normalized_tag = _normalize_member_tag(member.get("tag"))
    member_name = member.get("name")
    async with sessionmaker() as session:
        claim = (
            await session.execute(
                select(models.TargetClaim).where(
                    models.TargetClaim.event_type == event_type,
                    models.TargetClaim.event_key == event_key,
                    models.TargetClaim.enemy_position == enemy_position,
                )
            )
        ).scalar_one_or_none()
        user = None
        if normalized_tag:
            user = (
                await session.execute(
                    select(models.User).where(models.User.player_tag == normalized_tag)
                )
            ).scalar_one_or_none()
        if claim:
            claim.claimed_by_user_id = user.telegram_id if user else None
            claim.reserved_for_player_tag = normalized_tag
            claim.reserved_for_player_name = member_name
            claim.reserved_by_admin_id = admin_id
        else:
            session.add(
                models.TargetClaim(
                    war_id=war_row.id,
                    event_type=event_type,
                    event_key=event_key,
                    enemy_position=enemy_position,
                    claimed_by_user_id=user.telegram_id if user else None,
                    reserved_for_player_tag=normalized_tag,
                    reserved_for_player_name=member_name,
                    reserved_by_admin_id=admin_id,
                )
            )
        await session.commit()


async def _build_selection_markup(
    war: dict,
    war_row: models.War,
    sessionmaker: async_sessionmaker,
    user: models.User,
    admin_mode: bool,
    event_type: str,
    event_key: str | None,
) -> InlineKeyboardMarkup:
    enemies = _sorted_enemies(war.get("opponent", {}).get("members", []))
    claims = await _load_claims(sessionmaker, event_type, event_key)
    taken = {claim.enemy_position for claim in claims if claim.claimed_by_user_id != user.telegram_id}
    my_claims = {claim.enemy_position for claim in claims if claim.claimed_by_user_id == user.telegram_id}
    if _is_position_limit_active(war):
        max_position = None
        member_position = _resolve_member_position(war, user.player_tag)
        if member_position:
            max_position = member_position + 10
        if max_position:
            enemies = [
                enemy
                for enemy in enemies
                if (enemy.get("mapPosition") or 0) <= max_position
                or (enemy.get("mapPosition") in my_claims)
            ]
    admin_rows: list[tuple[str, str]] = []
    if admin_mode:
        for claim in claims:
            if claim.claimed_by_user_id == user.telegram_id:
                continue
            admin_rows.append(
                (
                    admin_unclaim_label(
                        claim.enemy_position,
                        _format_reserved_label(
                            claim.reserved_for_player_name,
                            claim.reserved_for_player_tag,
                        ),
                    ),
                    f"targets:admin-unclaim:{claim.enemy_position}",
                )
            )
    return build_targets_keyboard(
        enemies,
        mode="user",
        taken_positions=taken,
        my_positions=my_claims,
        admin_rows=admin_rows,
    )


async def _show_selection(
    message: Message,
    war: dict,
    war_row: models.War,
    sessionmaker: async_sessionmaker,
    user: models.User,
    admin_mode: bool,
    event_type: str,
    event_key: str | None,
) -> None:
    markup = await _build_selection_markup(war, war_row, sessionmaker, user, admin_mode, event_type, event_key)
    try:
        await message.answer(
            "Выберите противника:",
            reply_markup=markup,
        )
    except TelegramAPIError as exc:
        logger.exception("Failed to send targets selection (chat_id=%s): %s", message.chat.id, exc)


async def _refresh_selection(
    callback: CallbackQuery,
    war: dict,
    war_row: models.War,
    sessionmaker: async_sessionmaker,
    user: models.User,
    admin_mode: bool,
    event_type: str,
    event_key: str | None,
) -> None:
    markup = await _build_selection_markup(war, war_row, sessionmaker, user, admin_mode, event_type, event_key)
    if callback.message is None:
        logger.warning(
            "Failed to refresh selection: missing message (user_id=%s war_id=%s)",
            user.telegram_id,
            war_row.id,
        )
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=markup)
        return
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        logger.warning(
            "Failed to update selection markup (chat_id=%s message_id=%s): %s",
            callback.message.chat.id,
            callback.message.message_id,
            exc,
        )
    try:
        await callback.message.answer("Выберите противника:", reply_markup=markup)
        await _safe_delete_message(callback.message)
    except TelegramAPIError as exc:
        logger.exception(
            "Failed to refresh selection with fallback (chat_id=%s message_id=%s): %s",
            callback.message.chat.id,
            callback.message.message_id,
            exc,
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
    await reset_menu(state)
    await message.answer(
        "Раздел «Цели на войне».",
        reply_markup=_menu_reply(config, message.from_user.id),
    )


@router.message(F.text.in_(label_variants("targets")))
async def targets_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    await targets_command(message, state, config, coc_client, sessionmaker)


@router.message(F.text.in_(label_variants("targets_select")))
async def targets_select_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    logger.info(
        "Targets select button received (user_id=%s chat_id=%s text=%s)",
        message.from_user.id,
        message.chat.id,
        message.text,
    )
    await reset_state_if_any(state)
    war = await _load_war(coc_client, config.clan_tag)
    if not war:
        logger.info("Targets select blocked: war not active (reason=not_found)")
        await message.answer("Не удалось получить войну.", reply_markup=_menu_reply(config, message.from_user.id))
        return
    if war.get("state") != "preparation":
        logger.info(
            "Targets select blocked: war not active (state=%s)",
            war.get("state"),
        )
        await message.answer(
            "Выбор целей доступен только в подготовке.",
            reply_markup=_menu_reply(config, message.from_user.id),
        )
        return
    user = await _load_user(sessionmaker, message.from_user.id)
    if not user:
        logger.info("Targets select blocked: not registered (telegram_id=%s)", message.from_user.id)
        await message.answer(
            f"Вы ещё не зарегистрированы. Нажмите «{label('register')}».",
            reply_markup=_menu_reply(config, message.from_user.id),
        )
        return
    if not _is_user_in_war(user, war):
        logger.info(
            "Targets select blocked: not war participant (telegram_id=%s player_tag=%s)",
            message.from_user.id,
            user.player_tag,
        )
        await message.answer(
            "Ты не участвуешь в этой войне, поэтому не можешь выбирать цели.",
            reply_markup=_menu_reply(config, message.from_user.id),
        )
        return
    await send_hint_once(
        message,
        sessionmaker,
        user.telegram_id,
        "seen_hint_targets",
        TARGETS_HINT,
    )
    enemies = _sorted_enemies(war.get("opponent", {}).get("members", []))
    if not enemies:
        await message.answer("Нет списка противников.", reply_markup=_menu_reply(config, message.from_user.id))
        return
    event_type, event_key = _resolve_war_event(war, config.clan_tag)
    if not event_key:
        await message.answer("Не удалось определить текущую войну.", reply_markup=_menu_reply(config, message.from_user.id))
        return
    war_row = await _ensure_war_row(sessionmaker, war)
    await _show_selection(
        message,
        war,
        war_row,
        sessionmaker,
        user,
        is_admin(message.from_user.id, config),
        event_type,
        event_key,
    )


@router.message(F.text.in_(label_variants("targets_table")))
async def targets_table_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    logger.info(
        "Targets table button received (user_id=%s chat_id=%s text=%s)",
        message.from_user.id,
        message.chat.id,
        message.text,
    )
    await reset_state_if_any(state)
    war = await _load_war(coc_client, config.clan_tag)
    if not war:
        await message.answer("Не удалось получить войну.", reply_markup=_menu_reply(config, message.from_user.id))
        return
    enemies = _sorted_enemies(war.get("opponent", {}).get("members", []))
    if not enemies:
        await message.answer("Нет списка противников.", reply_markup=_menu_reply(config, message.from_user.id))
        return
    event_type, event_key = _resolve_war_event(war, config.clan_tag)
    if not event_key:
        await message.answer("Не удалось определить текущую войну.", reply_markup=_menu_reply(config, message.from_user.id))
        return
    war_row = await _ensure_war_row(sessionmaker, war)
    claims = await _load_claims(sessionmaker, event_type, event_key)
    table_chunks = await _build_table_messages(enemies, claims, sessionmaker)
    reply_markup = _menu_reply(config, message.from_user.id)
    for index, chunk in enumerate(table_chunks):
        await message.answer(
            chunk,
            reply_markup=reply_markup if index == 0 else None,
            parse_mode=ParseMode.HTML,
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
    logger.info(
        "Target claim callback received (user_id=%s chat_id=%s data=%s)",
        callback.from_user.id,
        callback.message.chat.id if callback.message else None,
        callback.data,
    )
    position = int(callback.data.split(":")[2])
    user_id = callback.from_user.id
    war = await _load_war(coc_client, config.clan_tag)
    if not war:
        logger.info("Target claim blocked: war not active (reason=not_found)")
        await callback.message.answer("Не удалось получить войну.")
        return
    if war.get("state") != "preparation":
        logger.info("Target claim blocked: war not active (state=%s)", war.get("state"))
        await callback.message.answer("Выбор целей доступен только в подготовке.")
        return
    war_row = await _ensure_war_row(sessionmaker, war)
    event_type, event_key = _resolve_war_event(war, config.clan_tag)
    if not event_key:
        await callback.message.answer("Не удалось определить текущую войну.")
        return
    user = await _load_user(sessionmaker, user_id)
    if not user:
        await callback.message.answer(f"Сначала зарегистрируйтесь. Нажмите «{label('register')}».")
        return
    if not _is_user_in_war(user, war):
        logger.info(
            "Target claim blocked: not war participant (telegram_id=%s player_tag=%s)",
            user_id,
            user.player_tag,
        )
        await callback.message.answer(
            "Ты не участвуешь в этой войне, поэтому не можешь выбирать цели."
        )
        return
    if not _is_target_position_allowed(war, user, position):
        await callback.answer(
            "Нельзя брать цель ниже чем на 10 позиций от своей (первые 12 часов).",
            show_alert=True,
        )
        await _refresh_selection(
            callback,
            war,
            war_row,
            sessionmaker,
            user,
            is_admin(user_id, config),
            event_type,
            event_key,
        )
        return
    logger.info("Target claim resolved war (user_id=%s war_id=%s position=%s)", user_id, war_row.id, position)

    result_action = None
    try:
        async with sessionmaker() as session:
            existing = (
                await session.execute(
                    select(models.TargetClaim).where(
                        models.TargetClaim.event_type == event_type,
                        models.TargetClaim.event_key == event_key,
                        models.TargetClaim.enemy_position == position,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                if existing.claimed_by_user_id == user_id:
                    await session.delete(existing)
                    result_action = "unclaimed"
                else:
                    holder = "другим игроком"
                    reserved_label = _format_reserved_label(
                        existing.reserved_for_player_name,
                        existing.reserved_for_player_tag,
                    )
                    if reserved_label:
                        holder = reserved_label
                    elif existing.claimed_by_user_id:
                        holder_user = (
                            await session.execute(
                                select(models.User).where(
                                    models.User.telegram_id == existing.claimed_by_user_id
                                )
                            )
                        ).scalar_one_or_none()
                        if holder_user:
                            holder_name = (
                                f"@{holder_user.username}"
                                if holder_user.username
                                else holder_user.player_name
                            )
                            holder = holder_name
                    logger.info(
                        "Target claim conflict (user_id=%s war_id=%s target_position=%s db_result=conflict)",
                        user_id,
                        war_row.id,
                        position,
                    )
                    await callback.message.answer(f"Цель уже занята: {holder}.")
                    await _refresh_selection(
                        callback,
                        war,
                        war_row,
                        sessionmaker,
                        user,
                        is_admin(user_id, config),
                        event_type,
                        event_key,
                    )
                    return
            else:
                claim_count = (
                    await session.execute(
                        select(func.count()).select_from(models.TargetClaim).where(
                            models.TargetClaim.event_type == event_type,
                            models.TargetClaim.event_key == event_key,
                            models.TargetClaim.claimed_by_user_id == user_id,
                        )
                    )
                ).scalar_one()
                if claim_count >= 2:
                    await callback.message.answer("Можно выбрать не более двух целей.")
                    await _refresh_selection(
                        callback,
                        war,
                        war_row,
                        sessionmaker,
                        user,
                        is_admin(user_id, config),
                        event_type,
                        event_key,
                    )
                    return
                session.add(
                    models.TargetClaim(
                        war_id=war_row.id,
                        event_type=event_type,
                        event_key=event_key,
                        enemy_position=position,
                        claimed_by_user_id=user_id,
                        reserved_for_player_tag=_normalize_member_tag(user.player_tag),
                        reserved_for_player_name=user.player_name,
                    )
                )
                result_action = "claimed"
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                logger.info(
                    "Target claim conflict (user_id=%s war_id=%s target_position=%s db_result=conflict)",
                    user_id,
                    war_row.id,
                    position,
                )
                await callback.message.answer("Цель уже занята другим игроком.")
                await _refresh_selection(
                    callback,
                    war,
                    war_row,
                    sessionmaker,
                    user,
                    is_admin(user_id, config),
                    event_type,
                    event_key,
                )
                return
            if result_action == "claimed":
                logger.info(
                    "Target claimed (user_id=%s war_id=%s target_position=%s db_result=created)",
                    user_id,
                    war_row.id,
                    position,
                )
            elif result_action == "unclaimed":
                logger.info(
                    "Target unclaimed (user_id=%s war_id=%s target_position=%s db_result=deleted)",
                    user_id,
                    war_row.id,
                    position,
                )
    except SQLAlchemyError as exc:
        logger.exception(
            "Failed to claim target (user_id=%s war_id=%s target_position=%s): %s",
            user_id,
            war_row.id,
            position,
            exc,
        )
        await callback.message.answer("Не удалось обновить цель. Попробуйте позже.")
        return

    await _refresh_selection(
        callback,
        war,
        war_row,
        sessionmaker,
        user,
        is_admin(user_id, config),
        event_type,
        event_key,
    )
    if result_action == "unclaimed":
        await callback.message.answer(f"Цель #{position} освобождена.")
    else:
        await callback.message.answer(f"Вы заняли цель #{position}.")


@router.callback_query(lambda c: c.data and c.data.startswith("targets:toggle:"))
async def target_toggle(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    await callback.answer("Обновляю…")
    await reset_state_if_any(state)
    logger.info(
        "Target toggle callback received (user_id=%s chat_id=%s data=%s)",
        callback.from_user.id,
        callback.message.chat.id if callback.message else None,
        callback.data,
    )
    position = int(callback.data.split(":")[2])
    user_id = callback.from_user.id
    war = await _load_war(coc_client, config.clan_tag)
    if not war:
        logger.info("Target toggle blocked: war not active (reason=not_found)")
        await callback.message.answer("Не удалось получить войну.")
        return
    if war.get("state") != "preparation":
        logger.info("Target toggle blocked: war not active (state=%s)", war.get("state"))
        await callback.message.answer("Выбор целей доступен только в подготовке.")
        return
    war_row = await _ensure_war_row(sessionmaker, war)
    event_type, event_key = _resolve_war_event(war, config.clan_tag)
    if not event_key:
        await callback.message.answer("Не удалось определить текущую войну.")
        return
    user = await _load_user(sessionmaker, user_id)
    if not user:
        await callback.message.answer(f"Сначала зарегистрируйтесь. Нажмите «{label('register')}».")
        return
    if not _is_user_in_war(user, war):
        logger.info(
            "Target toggle blocked: not war participant (telegram_id=%s player_tag=%s)",
            user_id,
            user.player_tag,
        )
        await callback.message.answer(
            "Ты не участвуешь в этой войне, поэтому не можешь выбирать цели."
        )
        return
    logger.info("Target toggle resolved war (user_id=%s war_id=%s position=%s)", user_id, war_row.id, position)
    try:
        async with sessionmaker() as session:
            claim = (
                await session.execute(
                    select(models.TargetClaim).where(
                        models.TargetClaim.event_type == event_type,
                        models.TargetClaim.event_key == event_key,
                        models.TargetClaim.enemy_position == position,
                        models.TargetClaim.claimed_by_user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            if not claim:
                await callback.message.answer("Эта цель недоступна.")
                await _refresh_selection(
                    callback,
                    war,
                    war_row,
                    sessionmaker,
                    user,
                    is_admin(user_id, config),
                    event_type,
                    event_key,
                )
                return
            await session.delete(claim)
            await session.commit()
            logger.info(
                "Target unclaimed (user_id=%s war_id=%s target_position=%s db_result=deleted)",
                user_id,
                war_row.id,
                position,
            )
    except SQLAlchemyError as exc:
        logger.exception(
            "Failed to unclaim target (user_id=%s war_id=%s target_position=%s): %s",
            user_id,
            war_row.id,
            position,
            exc,
        )
        await callback.message.answer("Не удалось обновить цель. Попробуйте позже.")
        return
    await _refresh_selection(
        callback,
        war,
        war_row,
        sessionmaker,
        user,
        is_admin(user_id, config),
        event_type,
        event_key,
    )
    await callback.message.answer(f"Цель #{position} освобождена.")


@router.callback_query(lambda c: c.data and c.data.startswith("targets:admin-unclaim:"))
async def target_admin_unclaim(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    await callback.answer("Снимаю…")
    await reset_state_if_any(state)
    logger.info(
        "Target admin-unclaim callback received (user_id=%s chat_id=%s data=%s)",
        callback.from_user.id,
        callback.message.chat.id if callback.message else None,
        callback.data,
    )
    if not is_admin(callback.from_user.id, config):
        await callback.message.answer("Доступно только администраторам.")
        return
    admin_user = await _load_user(sessionmaker, callback.from_user.id)
    if not admin_user:
        await callback.message.answer(f"Сначала зарегистрируйтесь. Нажмите «{label('register')}».")
        return
    position = int(callback.data.split(":")[2])
    war = await _load_war(coc_client, config.clan_tag)
    if not war:
        await callback.message.answer("Не удалось получить войну.")
        return
    war_row = await _ensure_war_row(sessionmaker, war)
    event_type, event_key = _resolve_war_event(war, config.clan_tag)
    if not event_key:
        await callback.message.answer("Не удалось определить текущую войну.")
        return
    logger.info(
        "Target admin-unclaim resolved war (user_id=%s war_id=%s position=%s)",
        callback.from_user.id,
        war_row.id,
        position,
    )
    try:
        async with sessionmaker() as session:
            claim = (
                await session.execute(
                    select(models.TargetClaim).where(
                        models.TargetClaim.event_type == event_type,
                        models.TargetClaim.event_key == event_key,
                        models.TargetClaim.enemy_position == position,
                    )
                )
            ).scalar_one_or_none()
            if not claim:
                await callback.message.answer("Цель уже свободна.")
                await _refresh_selection(
                    callback,
                    war,
                    war_row,
                    sessionmaker,
                    admin_user,
                    True,
                    event_type,
                    event_key,
                )
                return
            await session.delete(claim)
            await session.commit()
            logger.info(
                "Target admin-unclaimed (user_id=%s war_id=%s target_position=%s db_result=deleted)",
                callback.from_user.id,
                war_row.id,
                position,
            )
    except SQLAlchemyError as exc:
        logger.exception(
            "Failed to admin-unclaim target (user_id=%s war_id=%s target_position=%s): %s",
            callback.from_user.id,
            war_row.id,
            position,
            exc,
        )
        await callback.message.answer("Не удалось обновить цель. Попробуйте позже.")
        return
    await _refresh_selection(
        callback,
        war,
        war_row,
        sessionmaker,
        admin_user,
        True,
        event_type,
        event_key,
    )
    await callback.message.answer(f"Назначение для цели #{position} снято.")


@router.message(F.text.in_(label_variants("targets_assign")))
async def targets_assign_other(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    logger.info(
        "Targets assign button received (user_id=%s chat_id=%s text=%s)",
        message.from_user.id,
        message.chat.id,
        message.text,
    )
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer("Доступно только администраторам.")
        return
    war = await _load_war(coc_client, config.clan_tag)
    if not war:
        logger.info("Targets assign blocked: war not active (reason=not_found)")
        await message.answer("Не удалось получить войну.", reply_markup=_menu_reply(config, message.from_user.id))
        return
    if not _is_active_war_state(war.get("state")):
        logger.info("Targets assign blocked: war not active (state=%s)", war.get("state"))
        await message.answer(
            "Назначение целей доступно только во время активной войны.",
            reply_markup=_menu_reply(config, message.from_user.id),
        )
        return
    event_type, event_key = _resolve_war_event(war, config.clan_tag)
    if not event_key:
        await message.answer("Не удалось определить текущую войну.", reply_markup=_menu_reply(config, message.from_user.id))
        return
    await _send_admin_targets_list(message, None, war, sessionmaker, event_type, event_key)


@router.callback_query(lambda c: c.data and c.data.startswith("targets:admin-select:"))
async def targets_admin_select(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    await callback.answer("Открываю цель…")
    await reset_state_if_any(state)
    if not is_admin(callback.from_user.id, config):
        await callback.message.answer("Доступно только администраторам.")
        return
    position = int(callback.data.split(":")[2])
    war = await _load_war(coc_client, config.clan_tag)
    if not war:
        await callback.message.answer("Не удалось получить войну.")
        return
    if not _is_active_war_state(war.get("state")):
        await callback.message.answer("Назначение целей доступно только во время активной войны.")
        return
    event_type, event_key = _resolve_war_event(war, config.clan_tag)
    if not event_key:
        await callback.message.answer("Не удалось определить текущую войну.")
        return
    await _show_admin_target_details(callback, war, sessionmaker, event_type, event_key, position)


@router.callback_query(lambda c: c.data == "targets:admin-back")
async def targets_admin_back(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    await callback.answer("Обновляю…")
    await reset_state_if_any(state)
    if not is_admin(callback.from_user.id, config):
        await callback.message.answer("Доступно только администраторам.")
        return
    war = await _load_war(coc_client, config.clan_tag)
    if not war:
        await callback.message.answer("Не удалось получить войну.")
        return
    if not _is_active_war_state(war.get("state")):
        await callback.message.answer("Назначение целей доступно только во время активной войны.")
        return
    event_type, event_key = _resolve_war_event(war, config.clan_tag)
    if not event_key:
        await callback.message.answer("Не удалось определить текущую войну.")
        return
    await _send_admin_targets_list(None, callback, war, sessionmaker, event_type, event_key)


@router.callback_query(lambda c: c.data and c.data.startswith("targets:admin-assign:"))
async def targets_admin_assign(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
) -> None:
    await callback.answer("Выбирайте игрока…")
    await reset_state_if_any(state)
    if not is_admin(callback.from_user.id, config):
        await callback.message.answer("Доступно только администраторам.")
        return
    position = int(callback.data.split(":")[2])
    war = await _load_war(coc_client, config.clan_tag)
    if not war:
        await callback.message.answer("Не удалось получить войну.")
        return
    if not _is_active_war_state(war.get("state")):
        await callback.message.answer("Назначение целей доступно только во время активной войны.")
        return
    members = _sorted_members(war.get("clan", {}).get("members", []))
    if not members:
        await callback.message.answer("Нет списка участников войны.")
        return
    markup = targets_admin_members_kb(members, position=position, page=1)
    if callback.message:
        await callback.message.edit_text("Выберите участника войны:", reply_markup=markup)


@router.callback_query(lambda c: c.data and c.data.startswith("targets:admin-page:"))
async def targets_admin_members_page(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
) -> None:
    await callback.answer("Открываю страницу…")
    await reset_state_if_any(state)
    if not is_admin(callback.from_user.id, config):
        await callback.message.answer("Доступно только администраторам.")
        return
    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.message.answer("Не удалось переключить страницу.")
        return
    position = int(parts[2])
    page = int(parts[3])
    war = await _load_war(coc_client, config.clan_tag)
    if not war:
        await callback.message.answer("Не удалось получить войну.")
        return
    members = _sorted_members(war.get("clan", {}).get("members", []))
    if not members:
        await callback.message.answer("Нет списка участников войны.")
        return
    markup = targets_admin_members_kb(members, position=position, page=page)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=markup)


@router.callback_query(lambda c: c.data and c.data.startswith("targets:admin-pick:"))
async def targets_admin_pick_member(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    await callback.answer("Назначаю…")
    await reset_state_if_any(state)
    if not is_admin(callback.from_user.id, config):
        await callback.message.answer("Доступно только администраторам.")
        return
    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.message.answer("Не удалось определить игрока.")
        return
    position = int(parts[2])
    player_tag = normalize_tag(parts[3])
    war = await _load_war(coc_client, config.clan_tag)
    if not war:
        await callback.message.answer("Не удалось получить войну.")
        return
    if not _is_active_war_state(war.get("state")):
        await callback.message.answer("Назначение целей доступно только во время активной войны.")
        return
    event_type, event_key = _resolve_war_event(war, config.clan_tag)
    if not event_key:
        await callback.message.answer("Не удалось определить текущую войну.")
        return
    war_row = await _ensure_war_row(sessionmaker, war)
    member = _find_member_by_tag(war, player_tag)
    if not member:
        await callback.message.answer("Игрок не найден в текущей войне.")
        return
    await _assign_target_to_member(
        sessionmaker,
        war_row,
        event_type,
        event_key,
        position,
        member,
        callback.from_user.id,
    )
    logger.info(
        "Target assigned by admin (admin_id=%s position=%s member_tag=%s)",
        callback.from_user.id,
        position,
        player_tag,
    )
    await callback.answer("Назначено ✅")
    await _show_admin_target_details(callback, war, sessionmaker, event_type, event_key, position)


@router.callback_query(lambda c: c.data and c.data.startswith("targets:admin-release:"))
async def targets_admin_release(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    await callback.answer("Освобождаю…")
    await reset_state_if_any(state)
    if not is_admin(callback.from_user.id, config):
        await callback.message.answer("Доступно только администраторам.")
        return
    position = int(callback.data.split(":")[2])
    war = await _load_war(coc_client, config.clan_tag)
    if not war:
        await callback.message.answer("Не удалось получить войну.")
        return
    if not _is_active_war_state(war.get("state")):
        await callback.message.answer("Назначение целей доступно только во время активной войны.")
        return
    event_type, event_key = _resolve_war_event(war, config.clan_tag)
    if not event_key:
        await callback.message.answer("Не удалось определить текущую войну.")
        return
    released = await _admin_release_claim(
        sessionmaker,
        event_type,
        event_key,
        position,
        callback.from_user.id,
    )
    if not released:
        await callback.message.answer("Цель уже свободна.")
    await _send_admin_targets_list(None, callback, war, sessionmaker, event_type, event_key)


@router.callback_query(lambda c: c.data == "targets:none")
async def targets_no_available(callback: CallbackQuery) -> None:
    await callback.answer("Нет доступных целей.", show_alert=True)
