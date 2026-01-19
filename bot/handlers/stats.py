from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import main_menu_reply, stats_menu_reply
from bot.keyboards.seasons import seasons_kb
from bot.services.coc_client import CocClient
from bot.services.hints import send_hint_once
from bot.services.permissions import is_admin
from bot.texts.hints import STATS_HINT
from bot.texts.stats import STAT_LABELS
from bot.ui.labels import label, label_quoted
from bot.utils.navigation import reset_menu
from bot.utils.state import reset_state_if_any

router = Router()


def _format_stats(player: dict, war_summary: str | None, capital_summary: str | None) -> str:
    name = html.escape(str(player.get("name", "—")))
    tag = html.escape(str(player.get("tag", "—")))
    th = html.escape(str(player.get("townHallLevel", "—")))
    trophies = html.escape(str(player.get("trophies", "—")))
    donations = html.escape(str(player.get("donations", "—")))
    donations_received = html.escape(str(player.get("donationsReceived", "—")))
    war_stars = html.escape(str(player.get("warStars", "—")))
    attack_wins = html.escape(str(player.get("attackWins", "—")))
    defense_wins = html.escape(str(player.get("defenseWins", "—")))
    clan_name = html.escape(str(player.get("clan", {}).get("name", "—")))

    lines = [
        f"<b>{STAT_LABELS['profile']}</b>: {name} ({tag})",
        f"<b>{STAT_LABELS['clan']}</b>: {clan_name}",
        f"<b>{STAT_LABELS['townhall']}</b>: {th}",
        f"<b>{STAT_LABELS['trophies']}</b>: {trophies}",
        f"<b>{STAT_LABELS['donations']}</b>: {donations} / "
        f"{STAT_LABELS['donations_received'].lower()} {donations_received}",
        f"<b>{STAT_LABELS['war_stars']}</b>: {war_stars}",
        f"<b>{STAT_LABELS['attack_wins']}</b>: {attack_wins}",
        f"<b>{STAT_LABELS['defense_wins']}</b>: {defense_wins}",
    ]
    if war_summary:
        lines.append("")
        lines.append(war_summary)
    if capital_summary:
        lines.append("")
        lines.append(capital_summary)
    return "\n".join(lines)


async def _load_warlog_summary(coc_client: CocClient, clan_tag: str, player_tag: str) -> str | None:
    try:
        warlog = await coc_client.get_warlog(clan_tag)
    except Exception:  # noqa: BLE001
        return None
    items = warlog.get("items", [])
    total_attacks = 0
    total_stars = 0
    total_battles = 0
    for item in items:
        clan = item.get("clan", {})
        members = clan.get("members", [])
        for member in members:
            if member.get("tag") == player_tag:
                total_battles += 1
                total_attacks += member.get("attacks", 0)
                total_stars += member.get("stars", 0)
                break
    if total_battles == 0:
        return None
    attacks = html.escape(str(total_attacks))
    stars = html.escape(str(total_stars))
    battles = html.escape(str(total_battles))
    return f"<b>{STAT_LABELS['warlog']}</b>: {attacks} атак, {stars} ⭐ за {battles} войн"


async def _load_capital_summary(
    coc_client: CocClient,
    clan_tag: str,
    player_tag: str,
) -> str | None:
    try:
        raids = await coc_client.get_capital_raid_seasons(clan_tag)
    except Exception:  # noqa: BLE001
        return None
    items = raids.get("items", [])
    if not items:
        return None
    latest = items[0]
    members = latest.get("members", [])
    for member in members:
        if member.get("tag") == player_tag:
            attacks = member.get("attacks", 0)
            loot = member.get("capitalResourcesLooted", 0)
            return f"<b>{STAT_LABELS['capital']}</b>: {attacks} атак, золото {loot}"
    return None


@router.message(Command("mystats"))
async def mystats_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    await reset_state_if_any(state)
    await reset_menu(state)
    async with sessionmaker() as session:
        user = (
            await session.execute(select(models.User).where(models.User.telegram_id == message.from_user.id))
        ).scalar_one_or_none()
    if not user:
        await message.answer(
            f"Вы ещё не зарегистрированы. Нажмите {label_quoted('register')}.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    try:
        player = await coc_client.get_player(user.player_tag)
    except Exception:  # noqa: BLE001
        await message.answer(
            "Не удалось получить статистику из CoC API. Попробуйте позже.",
            reply_markup=stats_menu_reply(),
        )
        return

    war_summary = await _load_warlog_summary(coc_client, config.clan_tag, user.player_tag)
    capital_summary = await _load_capital_summary(coc_client, config.clan_tag, user.player_tag)
    await _send_or_edit_stats(message, sessionmaker, user, _format_stats(player, war_summary, capital_summary))
    await message.answer(
        "Экран статистики.",
        reply_markup=stats_menu_reply(),
    )
    await send_hint_once(
        message,
        sessionmaker,
        user.telegram_id,
        "seen_hint_stats",
        STATS_HINT,
    )


@router.message(Command("stats"))
async def stats_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    await mystats_command(message, state, config, sessionmaker, coc_client)


@router.message(Command("season"))
async def season_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    await reset_menu(state)
    async with sessionmaker() as session:
        seasons = (
            await session.execute(select(models.Season.id, models.Season.name).order_by(models.Season.end_at.desc()))
        ).all()
    if not seasons:
        await message.answer(
            "Сезоны появятся после первой ЛВК.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await message.answer("Выберите сезон:", reply_markup=seasons_kb(seasons))


@router.callback_query(lambda c: c.data and c.data.startswith("season:"))
async def season_callback(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    season_id = int(callback.data.split(":", 1)[1])
    await callback.message.answer(
        f"Сезон выбран: {season_id}.",
        reply_markup=stats_menu_reply(),
    )
    await callback.answer()
    await reset_state_if_any(state)


@router.message(F.text == label("stats"))
async def mystats_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    await mystats_command(message, state, config, sessionmaker, coc_client)


@router.message(F.text == label("refresh_stats"))
async def stats_refresh_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    await reset_state_if_any(state)
    async with sessionmaker() as session:
        user = (
            await session.execute(select(models.User).where(models.User.telegram_id == message.from_user.id))
        ).scalar_one_or_none()
    if not user:
        await message.answer(
            f"Вы ещё не зарегистрированы. Нажмите {label_quoted('register')}.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    try:
        player = await coc_client.get_player(user.player_tag)
    except Exception:  # noqa: BLE001
        await message.answer(
            "Не удалось получить статистику из CoC API. Попробуйте позже.",
            reply_markup=stats_menu_reply(),
        )
        return
    war_summary = await _load_warlog_summary(coc_client, config.clan_tag, user.player_tag)
    capital_summary = await _load_capital_summary(coc_client, config.clan_tag, user.player_tag)
    await _send_or_edit_stats(message, sessionmaker, user, _format_stats(player, war_summary, capital_summary))


async def _send_or_edit_stats(
    message: Message,
    sessionmaker: async_sessionmaker,
    user: models.User,
    text: str,
) -> None:
    async with sessionmaker() as session:
        user = (
            await session.execute(select(models.User).where(models.User.telegram_id == user.telegram_id))
        ).scalar_one()
        if user.last_stats_message_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=user.last_stats_message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                )
                return
            except Exception:  # noqa: BLE001
                pass
        sent = await message.answer(text, parse_mode=ParseMode.HTML)
        user.last_stats_message_id = sent.message_id
        await session.commit()
