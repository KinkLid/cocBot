from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import main_menu_reply, targets_admin_reply, targets_menu_reply
from bot.keyboards.targets import targets_select_kb
from bot.services.permissions import is_admin
from bot.services.coc_client import CocClient
from bot.services.hints import send_hint_once
from bot.texts.hints import TARGETS_HINT
from bot.ui.labels import admin_unclaim_label, is_back, is_main_menu, label, label_variants
from bot.utils.navigation import reset_menu
from bot.utils.state import reset_state_if_any
from bot.utils.validators import normalize_tag

logger = logging.getLogger(__name__)
router = Router()


class TargetsState(StatesGroup):
    waiting_external_name = State()


def _menu_reply(config: BotConfig, telegram_id: int):
    return targets_admin_reply() if is_admin(telegram_id, config) else targets_menu_reply()


def _sorted_enemies(enemies: list[dict]) -> list[dict]:
    return sorted(enemies, key=lambda enemy: enemy.get("mapPosition") or 0)


async def _load_war(coc_client: CocClient, clan_tag: str) -> dict | None:
    try:
        return await coc_client.get_current_war(clan_tag)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch war: %s", exc)
        return None


def _is_active_war_state(state: str | None) -> bool:
    return state in {"preparation", "inWar"}


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


async def _load_claims(sessionmaker: async_sessionmaker, war_id: int) -> list[models.TargetClaim]:
    async with sessionmaker() as session:
        return (
            await session.execute(select(models.TargetClaim).where(models.TargetClaim.war_id == war_id))
        ).scalars().all()


async def _load_user(sessionmaker: async_sessionmaker, telegram_id: int) -> models.User | None:
    async with sessionmaker() as session:
        return (
            await session.execute(select(models.User).where(models.User.telegram_id == telegram_id))
        ).scalar_one_or_none()


def _safe_text(value: str | None) -> str:
    if not value:
        return "?"
    return value.replace("`", "'").replace("\n", " ").replace("|", "/").strip()


def _truncate(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    if max_len <= 1:
        return value[:max_len]
    return f"{value[: max_len - 1]}…"


def _build_table_lines(
    enemies: list[dict],
    claims: list[models.TargetClaim],
    user_map: dict[int, models.User],
) -> list[str]:
    claims_map = {claim.enemy_position: claim for claim in claims}
    rows: list[tuple[str, str, str, str]] = []
    for enemy in _sorted_enemies(enemies):
        pos = str(enemy.get("mapPosition") or "?")
        name = _safe_text(enemy.get("name"))
        th = enemy.get("townhallLevel")
        enemy_label = f"{name} TH{th}" if th else name
        claim = claims_map.get(enemy.get("mapPosition"))
        if not claim:
            rows.append((pos, enemy_label, "свободно", "-"))
            continue
        if claim.external_player_name:
            holder = _safe_text(claim.external_player_name)
        elif claim.claimed_by_telegram_id:
            user = user_map.get(claim.claimed_by_telegram_id)
            if user:
                tg_name = f"@{user.username}" if user.username else user.player_name
                holder = _safe_text(f"{tg_name} / {user.player_name}")
            else:
                holder = "участник"
        else:
            holder = "участник"
        rows.append((pos, enemy_label, "занято", holder))

    if not rows:
        return ["Нет противников для отображения."]

    headers = ("№", "Противник", "Статус", "Кем занято")
    widths = [
        max(len(headers[0]), max(len(row[0]) for row in rows)),
        max(len(headers[1]), max(len(row[1]) for row in rows)),
        max(len(headers[2]), max(len(row[2]) for row in rows)),
        max(len(headers[3]), max(len(row[3]) for row in rows)),
    ]
    max_widths = [4, 22, 10, 22]
    widths = [min(widths[index], max_widths[index]) for index in range(len(widths))]

    lines = [
        "Таблица целей",
        "",
        " | ".join(
            [
                headers[0].ljust(widths[0]),
                headers[1].ljust(widths[1]),
                headers[2].ljust(widths[2]),
                headers[3].ljust(widths[3]),
            ]
        ),
        "-+-".join(["-" * width for width in widths]),
    ]
    for row in rows:
        lines.append(
            " | ".join(
                [
                    _truncate(row[0], widths[0]).ljust(widths[0]),
                    _truncate(row[1], widths[1]).ljust(widths[1]),
                    _truncate(row[2], widths[2]).ljust(widths[2]),
                    _truncate(row[3], widths[3]).ljust(widths[3]),
                ]
            )
        )
    return [html.escape(line) for line in lines]


def _chunk_lines(lines: list[str], max_chars: int = 3400) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1
        if current and current_len + line_len > max_chars:
            chunks.append(current)
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append(current)
    return chunks


async def _build_table_messages(
    enemies: list[dict],
    claims: list[models.TargetClaim],
    sessionmaker: async_sessionmaker,
) -> list[str]:
    async with sessionmaker() as session:
        users = (await session.execute(select(models.User))).scalars().all()
    user_map = {user.telegram_id: user for user in users}
    lines = _build_table_lines(enemies, claims, user_map)
    if lines and lines[0].startswith("Нет"):
        return ["\n".join(lines)]

    header_lines = lines[:4]
    data_lines = lines[4:]
    chunks: list[list[str]] = []
    if not data_lines:
        chunks = [lines]
    else:
        data_chunks = _chunk_lines(data_lines)
        for chunk in data_chunks:
            combined = [*header_lines, *chunk]
            chunks.append(combined)
    return ["\n".join(chunk) for chunk in chunks]


async def _build_selection_markup(
    war: dict,
    war_row: models.War,
    sessionmaker: async_sessionmaker,
    user_id: int,
    admin_mode: bool,
) -> InlineKeyboardMarkup:
    enemies = _sorted_enemies(war.get("opponent", {}).get("members", []))
    claims = await _load_claims(sessionmaker, war_row.id)
    taken = {claim.enemy_position for claim in claims if claim.claimed_by_telegram_id != user_id}
    my_claims = {claim.enemy_position for claim in claims if claim.claimed_by_telegram_id == user_id}
    admin_rows: list[tuple[str, str]] = []
    if admin_mode:
        for claim in claims:
            if claim.claimed_by_telegram_id == user_id:
                continue
            admin_rows.append(
                (
                    admin_unclaim_label(claim.enemy_position, claim.external_player_name),
                    f"targets:admin-unclaim:{claim.enemy_position}",
                )
            )
    return targets_select_kb(enemies, taken, my_claims, admin_rows=admin_rows)


async def _show_selection(
    message: Message,
    war: dict,
    war_row: models.War,
    sessionmaker: async_sessionmaker,
    user_id: int,
    admin_mode: bool,
) -> None:
    markup = await _build_selection_markup(war, war_row, sessionmaker, user_id, admin_mode)
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
    user_id: int,
    admin_mode: bool,
) -> None:
    markup = await _build_selection_markup(war, war_row, sessionmaker, user_id, admin_mode)
    if callback.message is None:
        logger.warning(
            "Failed to refresh selection: missing message (user_id=%s war_id=%s)",
            user_id,
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
    war_row = await _ensure_war_row(sessionmaker, war)
    await _show_selection(
        message,
        war,
        war_row,
        sessionmaker,
        message.from_user.id,
        is_admin(message.from_user.id, config),
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
    war_row = await _ensure_war_row(sessionmaker, war)
    claims = await _load_claims(sessionmaker, war_row.id)
    table_chunks = await _build_table_messages(enemies, claims, sessionmaker)
    reply_markup = _menu_reply(config, message.from_user.id)
    for index, chunk in enumerate(table_chunks):
        try:
            await message.answer(
                f"<pre>{chunk}</pre>",
                reply_markup=reply_markup if index == 0 else None,
                parse_mode=ParseMode.HTML,
            )
        except TelegramBadRequest as exc:
            logger.warning("Failed to send targets table, falling back: %s", exc)
            await message.answer(
                chunk,
                reply_markup=reply_markup if index == 0 else None,
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
    logger.info("Target claim resolved war (user_id=%s war_id=%s position=%s)", user_id, war_row.id, position)

    result_action = None
    try:
        async with sessionmaker() as session:
            existing = (
                await session.execute(
                    select(models.TargetClaim).where(
                        models.TargetClaim.war_id == war_row.id,
                        models.TargetClaim.enemy_position == position,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                if existing.claimed_by_telegram_id == user_id:
                    await session.delete(existing)
                    result_action = "unclaimed"
                else:
                    holder = "другим игроком"
                    if existing.external_player_name:
                        holder = existing.external_player_name
                    elif existing.claimed_by_telegram_id:
                        holder_user = (
                            await session.execute(
                                select(models.User).where(
                                    models.User.telegram_id == existing.claimed_by_telegram_id
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
                        user_id,
                        is_admin(user_id, config),
                    )
                    return
            else:
                claim_count = (
                    await session.execute(
                        select(func.count()).select_from(models.TargetClaim).where(
                            models.TargetClaim.war_id == war_row.id,
                            models.TargetClaim.claimed_by_telegram_id == user_id,
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
                        user_id,
                        is_admin(user_id, config),
                    )
                    return
                session.add(
                    models.TargetClaim(
                        war_id=war_row.id,
                        enemy_position=position,
                        claimed_by_telegram_id=user_id,
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
                    user_id,
                    is_admin(user_id, config),
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
        user_id,
        is_admin(user_id, config),
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
                        models.TargetClaim.war_id == war_row.id,
                        models.TargetClaim.enemy_position == position,
                        models.TargetClaim.claimed_by_telegram_id == user_id,
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
                    user_id,
                    is_admin(user_id, config),
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
        user_id,
        is_admin(user_id, config),
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
    position = int(callback.data.split(":")[2])
    war = await _load_war(coc_client, config.clan_tag)
    if not war:
        await callback.message.answer("Не удалось получить войну.")
        return
    war_row = await _ensure_war_row(sessionmaker, war)
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
                        models.TargetClaim.war_id == war_row.id,
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
                    callback.from_user.id,
                    True,
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
        callback.from_user.id,
        True,
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
    enemies = _sorted_enemies(war.get("opponent", {}).get("members", []))
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
    config: BotConfig,
) -> None:
    if not is_admin(callback.from_user.id, config):
        await callback.answer("Доступно только администраторам.")
        await callback.message.answer("Доступно только администраторам.")
        return
    await callback.answer("Введите ник игрока…")
    position = int(callback.data.split(":")[2])
    await state.update_data(assign_position=position)
    await state.set_state(TargetsState.waiting_external_name)
    await _safe_delete_message(
        callback.message,
        "Не удалось удалить сообщение. Проверьте права бота в чате.",
    )
    await callback.message.answer("Введите ник игрока в игре:")


@router.callback_query(lambda c: c.data == "targets:none")
async def targets_no_available(callback: CallbackQuery) -> None:
    await callback.answer("Нет доступных целей.", show_alert=True)


@router.message(TargetsState.waiting_external_name)
async def targets_assign_name(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
    sessionmaker: async_sessionmaker,
) -> None:
    if not is_admin(message.from_user.id, config):
        await state.clear()
        await message.answer("Доступно только администраторам.")
        return
    if is_main_menu(message.text):
        await state.clear()
        await reset_menu(state)
        await message.answer(
            "Главное меню.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    if is_back(message.text):
        await state.clear()
        await message.answer(
            "Действие отменено.",
            reply_markup=_menu_reply(config, message.from_user.id),
        )
        return
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
        logger.info("Targets assign blocked: war not active (reason=not_found)")
        await state.clear()
        await message.answer("Не удалось получить войну.", reply_markup=_menu_reply(config, message.from_user.id))
        return
    if not _is_active_war_state(war.get("state")):
        logger.info("Targets assign blocked: war not active (state=%s)", war.get("state"))
        await state.clear()
        await message.answer(
            "Назначение целей доступно только во время активной войны.",
            reply_markup=_menu_reply(config, message.from_user.id),
        )
        return
    war_row = await _ensure_war_row(sessionmaker, war)
    try:
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
                await session.rollback()
                logger.info(
                    "Target assign conflict (user_id=%s war_id=%s target_position=%s db_result=conflict)",
                    message.from_user.id,
                    war_row.id,
                    position,
                )
                await message.answer("Цель уже занята. Выберите другую.")
                await state.clear()
                return
            logger.info(
                "Target assigned (user_id=%s war_id=%s target_position=%s db_result=created)",
                message.from_user.id,
                war_row.id,
                position,
            )
    except SQLAlchemyError as exc:
        logger.exception(
            "Failed to assign external target (user_id=%s war_id=%s target_position=%s): %s",
            message.from_user.id,
            war_row.id,
            position,
            exc,
        )
        await message.answer("Не удалось назначить цель. Попробуйте позже.")
        await state.clear()
        return
    await state.clear()
    await message.answer(
        f"Назначено: цель #{position} за {name}.",
        reply_markup=_menu_reply(config, message.from_user.id),
    )
