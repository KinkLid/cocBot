from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.services.coc_client import CocClient
from bot.utils.coc_time import parse_coc_time

logger = logging.getLogger(__name__)

DEFAULT_CHAT_TYPES = {
    "preparation": True,
    "inWar": True,
    "warEnded": True,
    "cwlEnded": True,
}


class NotificationService:
    def __init__(
        self,
        bot: Bot,
        config: BotConfig,
        sessionmaker: async_sessionmaker,
        coc_client: CocClient,
    ) -> None:
        self._bot = bot
        self._config = config
        self._sessionmaker = sessionmaker
        self._coc = coc_client

    async def poll_war_state(self) -> None:
        try:
            war_data = await self._coc.get_current_war(self._config.clan_tag)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load current war: %s", exc)
            return
        state = war_data.get("state", "unknown")
        war_tag = war_data.get("tag") or war_data.get("clan", {}).get("tag")
        start_at = parse_coc_time(war_data.get("startTime"))
        end_at = parse_coc_time(war_data.get("endTime"))
        async with self._sessionmaker() as session:
            war_row = None
            if war_tag:
                war_row = (
                    await session.execute(select(models.War).where(models.War.war_tag == war_tag))
                ).scalar_one_or_none()
            if not war_row:
                war_row = models.War(
                    war_tag=war_tag,
                    war_type=war_data.get("warType", "unknown"),
                    state=state,
                    start_at=start_at,
                    end_at=end_at,
                    opponent_name=war_data.get("opponent", {}).get("name"),
                    opponent_tag=war_data.get("opponent", {}).get("tag"),
                    league_name=war_data.get("league", {}).get("name"),
                )
                session.add(war_row)
                await session.flush()
            else:
                war_row.state = state
                war_row.start_at = start_at or war_row.start_at
                war_row.end_at = end_at or war_row.end_at
                war_row.opponent_name = war_data.get("opponent", {}).get("name") or war_row.opponent_name
                war_row.opponent_tag = war_data.get("opponent", {}).get("tag") or war_row.opponent_tag
                war_row.league_name = war_data.get("league", {}).get("name") or war_row.league_name

            war_state = None
            if war_tag:
                war_state = (
                    await session.execute(select(models.WarState).where(models.WarState.war_tag == war_tag))
                ).scalar_one_or_none()
            if not war_state:
                war_state = models.WarState(
                    war_tag=war_tag,
                    state=state,
                    last_notified_state=state,
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(war_state)
                await session.commit()
                return

            previous_state = war_state.state
            war_state.state = state
            war_state.updated_at = datetime.now(timezone.utc)
            await session.commit()

        if previous_state != state and state in {"preparation", "inWar", "warEnded"}:
            await self._notify_war_state(state, war_data)
            async with self._sessionmaker() as session:
                await session.execute(
                    update(models.WarState)
                    .where(models.WarState.war_tag == war_tag)
                    .values(last_notified_state=state, updated_at=datetime.now(timezone.utc))
                )
                if state == "warEnded" and war_row:
                    await session.execute(
                        update(models.WarReminder)
                        .where(models.WarReminder.war_id == war_row.id)
                        .where(models.WarReminder.status == "pending")
                        .values(status="canceled")
                    )
                await session.commit()

    async def dispatch_war_reminders(self) -> None:
        now = datetime.now(timezone.utc)
        async with self._sessionmaker() as session:
            reminders = (
                await session.execute(
                    select(models.WarReminder, models.War)
                    .join(models.War, models.War.id == models.WarReminder.war_id)
                    .where(models.WarReminder.status == "pending")
                    .where(models.WarReminder.fire_at <= now)
                )
            ).all()
            if not reminders:
                return
            for reminder, war in reminders:
                if war.state == "warEnded":
                    reminder.status = "canceled"
                    continue
                try:
                    await self._bot.send_message(
                        chat_id=self._config.main_chat_id,
                        text=f"⏰ Напоминание по войне: {reminder.message_text}",
                    )
                    reminder.status = "sent"
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to send reminder %s: %s", reminder.id, exc)
                    reminder.status = "failed"
            await session.commit()

    async def poll_cwl_state(self) -> None:
        try:
            data = await self._coc.get_league_group(self._config.clan_tag)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load CWL league group: %s", exc)
            return
        season = data.get("season") or datetime.now(timezone.utc).strftime("%Y-%m")
        state = data.get("state", "unknown")
        async with self._sessionmaker() as session:
            cwl_state = (
                await session.execute(select(models.CwlState).where(models.CwlState.season == season))
            ).scalar_one_or_none()
            if not cwl_state:
                cwl_state = models.CwlState(
                    season=season,
                    state=state,
                    notified=False,
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(cwl_state)
                await session.commit()
                return
            cwl_state.state = state
            cwl_state.updated_at = datetime.now(timezone.utc)
            await session.commit()

        if state == "ended" and not cwl_state.notified:
            await self._notify_cwl_end(season)
            async with self._sessionmaker() as session:
                await session.execute(
                    update(models.CwlState)
                    .where(models.CwlState.season == season)
                    .values(notified=True, updated_at=datetime.now(timezone.utc))
                )
                await session.commit()

    async def _notify_war_state(self, state: str, war_data: dict[str, Any]) -> None:
        opponent = war_data.get("opponent", {}).get("name") or "противник"
        if state == "preparation":
            text = (
                "🛡 Началась подготовка к войне.\n"
                f"Противник: {opponent}\n"
                "Выберите цели через «Цели на войне» → «Выбрать противников»."
            )
            dm_text = f"Началась подготовка к войне против {opponent}. Пора выбрать цели."
            notify_type = "preparation"
        elif state == "inWar":
            text = f"⚔️ Началась война против {opponent}."
            dm_text = text
            notify_type = "inWar"
        else:
            clan = war_data.get("clan", {})
            enemy = war_data.get("opponent", {})
            result = _format_war_result(clan, enemy)
            score = f"{clan.get('stars', 0)}:{enemy.get('stars', 0)}"
            destruction = None
            if clan.get("destructionPercentage") is not None:
                destruction = f"{clan.get('destructionPercentage', 0)}% : {enemy.get('destructionPercentage', 0)}%"
            text = f"🏁 Война завершена: {result}\nСчёт звёзд: {score}"
            if destruction:
                text += f"\nРазрушение: {destruction}"
            dm_text = "Война закончилась. Посмотрите итоги!"
            notify_type = "warEnded"

        await self._send_chat_notification(text, notify_type)
        await self._send_dm_notifications(dm_text, notify_type)

    async def _notify_cwl_end(self, season: str) -> None:
        header = f"🏆 ЛВК завершена ({season}). Итоги месяца:"
        sections = []
        stats = await self._collect_cwl_stats()
        if stats["war_stars"]:
            sections.append(_format_top_list("⭐ Звёзды войны", stats["war_stars"]))
        if stats["donations"]:
            sections.append(_format_top_list("🎁 Донаты", stats["donations"]))
        if stats["capital"]:
            sections.append(_format_top_list("🏗 Вклад в столицу", stats["capital"]))
        if not sections:
            sections.append("Нет данных для топов. Запустите сбор статистики заранее.")
        text = "\n\n".join([header, *sections])
        await self._send_chat_notification(text, "cwlEnded")
        await self._send_dm_notifications("ЛВК завершена. Итоги опубликованы в общем чате.", "cwlEnded")

    async def _collect_cwl_stats(self) -> dict[str, list[tuple[str, int]]]:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=30)
        stats: dict[str, list[tuple[str, int]]] = {"war_stars": [], "donations": [], "capital": []}
        async with self._sessionmaker() as session:
            users = (await session.execute(select(models.User))).scalars().all()
            snapshots = (
                await session.execute(
                    select(models.StatsDaily)
                    .where(models.StatsDaily.captured_at >= window_start)
                    .order_by(models.StatsDaily.captured_at.asc())
                )
            ).scalars().all()
        per_user: dict[int, list[models.StatsDaily]] = defaultdict(list)
        for snap in snapshots:
            per_user[snap.telegram_id].append(snap)
        for user in users:
            user_snaps = per_user.get(user.telegram_id, [])
            if len(user_snaps) >= 2:
                first = user_snaps[0].payload
                last = user_snaps[-1].payload
                war_delta = (last.get("war_stars", 0) or 0) - (first.get("war_stars", 0) or 0)
                donate_delta = (last.get("donations", 0) or 0) - (first.get("donations", 0) or 0)
                if war_delta > 0:
                    stats["war_stars"].append((user.player_name, war_delta))
                if donate_delta > 0:
                    stats["donations"].append((user.player_name, donate_delta))
        try:
            raids = await self._coc.get_capital_raid_seasons(self._config.clan_tag)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load capital raids: %s", exc)
        else:
            items = raids.get("items", [])
            if items:
                latest = items[0]
                for member in latest.get("members", []):
                    stats["capital"].append(
                        (member.get("name", "Игрок"), member.get("capitalResourcesLooted", 0))
                    )
        for key in stats:
            stats[key] = sorted(stats[key], key=lambda x: x[1], reverse=True)[:5]
        return stats

    async def _send_chat_notification(self, text: str, notify_type: str) -> None:
        if not await self._chat_type_enabled(notify_type):
            return
        await self._bot.send_message(chat_id=self._config.main_chat_id, text=text)

    async def send_test_notification(self, notify_type: str) -> None:
        samples = {
            "preparation": "🧪 Тест W1: подготовка к войне.",
            "inWar": "🧪 Тест W2: война началась.",
            "warEnded": "🧪 Тест W3: война завершена.",
            "cwlEnded": "🧪 Тест W4: ЛВК завершена.",
        }
        text = samples.get(notify_type)
        if not text:
            return
        await self._send_chat_notification(text, notify_type)
        await self._send_dm_notifications(text, notify_type)

    async def _send_dm_notifications(self, text: str, notify_type: str) -> None:
        async with self._sessionmaker() as session:
            users = (await session.execute(select(models.User))).scalars().all()
            for user in users:
                prefs = _normalize_user_pref(user.notify_pref)
                if not prefs.get("dm_enabled", False):
                    continue
                if not prefs.get("dm_types", {}).get(notify_type, False):
                    continue
                if not _is_within_dm_window(prefs, self._config.timezone):
                    continue
                try:
                    await self._bot.send_message(chat_id=user.telegram_id, text=text)
                except TelegramForbiddenError:
                    prefs["dm_enabled"] = False
                    user.notify_pref = prefs
                    await session.commit()
                    logger.info("Disabled DM notifications for telegram_id=%s", user.telegram_id)

    async def _chat_type_enabled(self, notify_type: str) -> bool:
        async with self._sessionmaker() as session:
            settings = (
                await session.execute(
                    select(models.ChatNotificationSetting).where(
                        models.ChatNotificationSetting.chat_id == self._config.main_chat_id
                    )
                )
            ).scalar_one_or_none()
            if not settings:
                settings = models.ChatNotificationSetting(
                    chat_id=self._config.main_chat_id, preferences={"types": DEFAULT_CHAT_TYPES}
                )
                session.add(settings)
                await session.commit()
                return DEFAULT_CHAT_TYPES.get(notify_type, True)
            prefs = dict(settings.preferences or {})
            types = dict(DEFAULT_CHAT_TYPES)
            types.update(prefs.get("types", {}) or {})
            return bool(types.get(notify_type, True))


def _normalize_user_pref(pref: dict | None) -> dict[str, Any]:
    pref = dict(pref or {})
    pref.setdefault("dm_enabled", False)
    types = {
        "preparation": True,
        "inWar": True,
        "warEnded": True,
        "cwlEnded": False,
    }
    types.update(pref.get("dm_types", {}) or {})
    pref["dm_types"] = types
    pref.setdefault("dm_window", "always")
    return pref


def _is_within_dm_window(pref: dict[str, Any], tz_name: str) -> bool:
    if pref.get("dm_window") == "always":
        return True
    zone = ZoneInfo(tz_name)
    now_local = datetime.now(zone)
    start = now_local.replace(hour=9, minute=0, second=0, microsecond=0)
    end = now_local.replace(hour=22, minute=0, second=0, microsecond=0)
    return start <= now_local <= end


def _format_war_result(clan: dict[str, Any], enemy: dict[str, Any]) -> str:
    clan_stars = clan.get("stars", 0)
    enemy_stars = enemy.get("stars", 0)
    if clan_stars > enemy_stars:
        return "победа"
    if clan_stars < enemy_stars:
        return "поражение"
    clan_destr = clan.get("destructionPercentage", 0)
    enemy_destr = enemy.get("destructionPercentage", 0)
    if clan_destr > enemy_destr:
        return "победа"
    if clan_destr < enemy_destr:
        return "поражение"
    return "ничья"


def _format_top_list(title: str, items: list[tuple[str, int]]) -> str:
    if not items:
        return f"{title}: нет данных."
    lines = [title]
    for index, (name, value) in enumerate(items, start=1):
        lines.append(f"{index}. {name} — {value}")
    return "\n".join(lines)
