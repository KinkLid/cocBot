from __future__ import annotations

from aiogram import F, Router
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
from bot.services.permissions import is_admin
from bot.utils.state import reset_state_if_any

router = Router()


def _format_stats(player: dict, war_summary: str | None, capital_summary: str | None) -> str:
    name = player.get("name", "—")
    tag = player.get("tag", "—")
    th = player.get("townHallLevel", "—")
    trophies = player.get("trophies", "—")
    donations = player.get("donations", "—")
    donations_received = player.get("donationsReceived", "—")
    war_stars = player.get("warStars", "—")
    attack_wins = player.get("attackWins", "—")
    defense_wins = player.get("defenseWins", "—")
    clan_name = player.get("clan", {}).get("name", "—")

    lines = [
        f"*Профиль*: {name} ({tag})",
        f"*Клан*: {clan_name}",
        f"*TH*: {th}",
        f"*Трофеи*: {trophies}",
        f"*Донаты*: {donations} / получено {donations_received}",
        f"*War stars*: {war_stars}",
        f"*Attack wins*: {attack_wins}",
        f"*Defense wins*: {defense_wins}",
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
    return f"*Warlog*: {total_attacks} атак, {total_stars} ⭐ за {total_battles} войн"


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
            return f"*Столица*: {attacks} атак, золото {loot}"
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
    async with sessionmaker() as session:
        user = (
            await session.execute(select(models.User).where(models.User.telegram_id == message.from_user.id))
        ).scalar_one_or_none()
    if not user:
        await message.answer(
            "Вы ещё не зарегистрированы. Нажмите «Регистрация».",
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
        "Админская статистика доступна через админ-панель.",
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


@router.message(F.text == "Моя статистика")
async def mystats_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    await mystats_command(message, state, config, sessionmaker, coc_client)


@router.message(F.text == "Обновить статистику")
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
            "Вы ещё не зарегистрированы. Нажмите «Регистрация».",
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
                    parse_mode="Markdown",
                )
                return
            except Exception:  # noqa: BLE001
                pass
        sent = await message.answer(text, parse_mode="Markdown")
        user.last_stats_message_id = sent.message_id
        await session.commit()
