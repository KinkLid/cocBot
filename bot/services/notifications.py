from __future__ import annotations

import html
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.services.coc_client import CocClient
from bot.utils.coc_time import parse_coc_time
from bot.utils.notify_time import format_duration_ru
from bot.utils.war_attacks import build_missed_attacks_table, build_total_attacks_table, collect_missed_attacks

logger = logging.getLogger(__name__)

DEFAULT_CHAT_PREFS = {
    "war": {
        "preparation": True,
        "start": True,
        "end": True,
        "reminder": True,
    },
    "cwl": {
        "round_start": True,
        "round_end": True,
        "reminder": True,
        "monthly_summary": True,
    },
    "capital": {
        "start": True,
        "end": True,
        "reminder": True,
    },
}

EVENT_CATEGORY_MAP = {
    "war_preparation": ("war", "preparation"),
    "war_start": ("war", "start"),
    "war_end": ("war", "end"),
    "war_reminder": ("war", "reminder"),
    "cwl_round_start": ("cwl", "round_start"),
    "cwl_round_end": ("cwl", "round_end"),
    "cwl_reminder": ("cwl", "reminder"),
    "capital_start": ("capital", "start"),
    "capital_end": ("capital", "end"),
    "capital_reminder": ("capital", "reminder"),
    "monthly_summary": ("cwl", "monthly_summary"),
}

DEFAULT_DM_CATEGORIES = {
    "war": False,
    "cwl": False,
    "capital": False,
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
            if state in {"preparation", "inWar"} and previous_state not in {"preparation", "inWar"}:
                await self._schedule_rule_instances(
                    event_type="war",
                    event_id=war_tag,
                    start_at=start_at,
                )
            await self._notify_war_state(state, war_data)
            async with self._sessionmaker() as session:
                await session.execute(
                    update(models.WarState)
                    .where(models.WarState.war_tag == war_tag)
                    .values(last_notified_state=state, updated_at=datetime.now(timezone.utc))
                )
                if state == "warEnded" and war_tag:
                    await self._cancel_rule_instances(session, war_tag)
                await session.execute(
                    update(models.ScheduledNotification)
                    .where(models.ScheduledNotification.category == "war")
                    .where(models.ScheduledNotification.status == "pending")
                    .values(status="canceled")
                )
                await session.commit()

    async def dispatch_scheduled_notifications(self) -> None:
        now = datetime.now(timezone.utc)
        async with self._sessionmaker() as session:
            await self._dispatch_rule_instances(session, now)
            reminders = (
                await session.execute(
                    select(models.ScheduledNotification)
                    .where(models.ScheduledNotification.status == "pending")
                    .where(models.ScheduledNotification.fire_at <= now)
                )
            ).scalars().all()
            if not reminders:
                return
            for reminder in reminders:
                try:
                    text = await self._build_reminder_message(reminder)
                    if text:
                        scope = reminder.context.get("scope", "chat")
                        if scope == "dm":
                            await self._send_reminder_dm(reminder, text)
                        else:
                            await self._send_chat_notification(text, reminder.event_type)
                        reminder.status = "sent"
                    else:
                        reminder.status = "canceled"
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
            else:
                cwl_state.state = state
                cwl_state.updated_at = datetime.now(timezone.utc)
                await session.commit()

        current_war = await self._find_current_cwl_war(data)
        if current_war:
            await self._sync_cwl_war(current_war, season)

        if state == "ended" and cwl_state and not cwl_state.notified:
            await self._notify_cwl_end(season)
            async with self._sessionmaker() as session:
                await session.execute(
                    update(models.CwlState)
                    .where(models.CwlState.season == season)
                    .values(notified=True, updated_at=datetime.now(timezone.utc))
                )
                await session.commit()

    async def poll_capital_state(self) -> None:
        try:
            raids = await self._coc.get_capital_raid_seasons(self._config.clan_tag)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load capital raids: %s", exc)
            return
        items = raids.get("items", [])
        if not items:
            return
        latest = items[0]
        raid_id = latest.get("startTime") or latest.get("endTime") or "raid"
        start_at = parse_coc_time(latest.get("startTime"))
        end_at = parse_coc_time(latest.get("endTime"))
        now = datetime.now(timezone.utc)
        state = "active" if start_at and end_at and start_at <= now <= end_at else "ended"
        async with self._sessionmaker() as session:
            raid_state = (
                await session.execute(
                    select(models.CapitalRaidState).where(models.CapitalRaidState.raid_id == raid_id)
                )
            ).scalar_one_or_none()
            if not raid_state:
                raid_state = models.CapitalRaidState(
                    raid_id=raid_id,
                    state=state,
                    last_notified_state=None,
                    updated_at=now,
                )
                session.add(raid_state)
                await session.commit()
            else:
                raid_state.state = state
                raid_state.updated_at = now
                await session.commit()

        if raid_state.last_notified_state != state:
            if state == "active":
                text = self._format_capital_start(latest)
                await self._send_event(text, "capital_start")
                await self._schedule_rule_instances(
                    event_type="capital",
                    event_id=raid_id,
                    start_at=start_at,
                )
            elif state == "ended":
                text = self._format_capital_end(latest)
                await self._send_event(text, "capital_end")
            async with self._sessionmaker() as session:
                await session.execute(
                    update(models.CapitalRaidState)
                    .where(models.CapitalRaidState.raid_id == raid_id)
                    .values(last_notified_state=state, updated_at=now)
                )
                if state == "ended":
                    await self._cancel_rule_instances(session, raid_id)
                await session.commit()

    async def _notify_war_state(self, state: str, war_data: dict[str, Any]) -> None:
        opponent = html.escape(war_data.get("opponent", {}).get("name") or "противник")
        if state == "preparation":
            text = (
                "<b>🛡 Началась подготовка к войне.</b>\n"
                f"Противник: {opponent}\n"
                "Нажмите «Цели на войне» → «Выбрать противника»."
            )
            dm_text = f"Началась подготовка к войне против {opponent}."
            notify_type = "war_preparation"
        elif state == "inWar":
            text = f"<b>⚔️ Началась Клановая война против {opponent}!</b>\nУдачи в бою!"
            dm_text = f"Началась Клановая война против {opponent}! Удачи в бою!"
            notify_type = "war_start"
        else:
            clan, enemy = _resolve_war_sides(war_data, self._config.clan_tag)
            result = _format_war_result(clan, enemy)
            score = f"{clan.get('stars', 0)}:{enemy.get('stars', 0)}"
            destruction = None
            if clan.get("destructionPercentage") is not None:
                destruction = f"{clan.get('destructionPercentage', 0)}% : {enemy.get('destructionPercentage', 0)}%"
            text = (
                f"<b>🏁 КВ против {opponent} завершилась: {result}</b>\n"
                f"Счёт звёзд: {score}"
            )
            if destruction:
                text += f"\nРазрушение: {destruction}"
            missing_table = _build_missing_attacks_section(
                war_data,
                self._config.clan_tag,
                title="Кто не атаковал",
            )
            if missing_table:
                text += f"\n\n{missing_table}"
            dm_text = text
            notify_type = "war_end"

        await self._send_chat_notification(text, notify_type)
        await self._send_dm_notifications(dm_text, notify_type)

    async def _notify_cwl_end(self, season: str) -> None:
        header = f"<b>🏆 ЛВК завершена ({season}). Итоги месяца:</b>"
        sections = []
        stats = await self._collect_cwl_stats()
        if stats["war_stars"]:
            sections.append(_format_top_list("⭐ Звёзды войны", stats["war_stars"]))
        if stats["donations"]:
            sections.append(_format_top_list("🎁 Донаты", stats["donations"]))
        if stats["capital"]:
            sections.append(_format_top_list("🏗 Вклад в столицу", stats["capital"]))
        if not sections:
            sections.append("Данных пока недостаточно для топов.")
        summary = await self._collect_cwl_attack_summary()
        if summary:
            sections.append("Кто сколько атак сделал:")
            sections.append(summary)
        text = "\n\n".join([header, *sections])
        await self._send_chat_notification(text, "monthly_summary")
        await self._send_dm_notifications("ЛВК завершена. Итоги опубликованы в общем чате.", "monthly_summary")

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

    async def _sync_cwl_war(self, war: dict[str, Any], season: str) -> None:
        war_tag = war.get("tag")
        if not war_tag:
            return
        state = war.get("state", "unknown")
        async with self._sessionmaker() as session:
            war_state = (
                await session.execute(select(models.CwlWarState).where(models.CwlWarState.war_tag == war_tag))
            ).scalar_one_or_none()
            if not war_state:
                war_state = models.CwlWarState(
                    season=season,
                    war_tag=war_tag,
                    state=state,
                    last_notified_state=None,
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(war_state)
                await session.commit()
            else:
                war_state.state = state
                war_state.updated_at = datetime.now(timezone.utc)
                await session.commit()

        if war_state.last_notified_state != state and state in {"preparation", "inWar", "warEnded"}:
            if state in {"preparation", "inWar"}:
                if war_state.last_notified_state not in {"preparation", "inWar"}:
                    start_at = parse_coc_time(war.get("startTime"))
                    await self._schedule_rule_instances("cwl", war_tag, start_at)
                text = self._format_cwl_start(war)
                await self._send_event(text, "cwl_round_start")
            else:
                text = self._format_cwl_end(war)
                await self._send_event(text, "cwl_round_end")
            async with self._sessionmaker() as session:
                await session.execute(
                    update(models.CwlWarState)
                    .where(models.CwlWarState.war_tag == war_tag)
                    .values(last_notified_state=state, updated_at=datetime.now(timezone.utc))
                )
                if state == "warEnded":
                    await self._cancel_rule_instances(session, war_tag)
                await session.commit()

    async def _find_current_cwl_war(self, league: dict[str, Any]) -> dict[str, Any] | None:
        rounds = league.get("rounds", [])
        for round_item in rounds:
            for tag in round_item.get("warTags", []):
                if tag and tag != "#0":
                    try:
                        war = await self._coc.get_cwl_war(tag)
                    except Exception:  # noqa: BLE001
                        continue
                    if war.get("state") in {"preparation", "inWar"}:
                        return war
        for round_item in reversed(rounds):
            for tag in round_item.get("warTags", []):
                if tag and tag != "#0":
                    try:
                        war = await self._coc.get_cwl_war(tag)
                    except Exception:  # noqa: BLE001
                        continue
                    return war
        return None

    async def _build_reminder_message(self, reminder: models.ScheduledNotification) -> str | None:
        description = html.escape(reminder.message_text or "")
        delay_minutes = reminder.context.get("delay_minutes")
        delay_text = format_duration_ru(delay_minutes) if isinstance(delay_minutes, int) else None
        if reminder.category == "war":
            war_data = await self._coc.get_current_war(self._config.clan_tag)
            if reminder.context.get("war_tag") and war_data.get("tag") != reminder.context.get("war_tag"):
                return None
            opponent = html.escape(war_data.get("opponent", {}).get("name") or "противник")
            snapshot = _build_war_snapshot(war_data)
            header = "⏰ Напоминание о войне"
            if delay_text:
                header = f"⏰ Прошло {delay_text} с начала войны против {opponent}"
            parts = [f"<b>{header}</b>"]
            if description:
                parts.append(description)
            parts.append("")
            parts.append(snapshot)
            return "\n".join(parts)
        if reminder.category == "cwl":
            war_tag = reminder.context.get("cwl_war_tag")
            if not war_tag:
                return None
            war_data = await self._coc.get_cwl_war(war_tag)
            opponent = html.escape(war_data.get("opponent", {}).get("name") or "противник")
            snapshot = _build_war_snapshot(war_data)
            header = "⏰ Напоминание ЛВК"
            if delay_text:
                header = f"⏰ Прошло {delay_text} с начала раунда ЛВК против {opponent}"
            parts = [f"<b>{header}</b>"]
            if description:
                parts.append(description)
            parts.append("")
            parts.append(snapshot)
            return "\n".join(parts)
        if reminder.category == "capital":
            raids = await self._coc.get_capital_raid_seasons(self._config.clan_tag)
            items = raids.get("items", [])
            if not items:
                return None
            latest = items[0]
            snapshot = _build_capital_snapshot(latest)
            header = "⏰ Напоминание по столице"
            if delay_text:
                header = f"⏰ Прошло {delay_text} с начала рейдов столицы"
            parts = [f"<b>{header}</b>"]
            if description:
                parts.append(description)
            parts.append("")
            parts.append(snapshot)
            return "\n".join(parts)
        return None

    async def _schedule_rule_instances(
        self,
        event_type: str,
        event_id: str | None,
        start_at: datetime | None,
    ) -> None:
        if not event_id or not start_at:
            return
        async with self._sessionmaker() as session:
            existing_rule_ids = set(
                (
                    await session.execute(
                        select(models.NotificationInstance.rule_id).where(
                            models.NotificationInstance.event_id == event_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            rules = (
                await session.execute(
                    select(models.NotificationRule).where(
                        models.NotificationRule.event_type == event_type,
                        models.NotificationRule.is_enabled.is_(True),
                    )
                )
            ).scalars().all()
            for rule in rules:
                if rule.id in existing_rule_ids:
                    continue
                fire_at = start_at + timedelta(seconds=rule.delay_seconds)
                session.add(
                    models.NotificationInstance(
                        rule_id=rule.id,
                        event_id=event_id,
                        fire_at=fire_at,
                        status="pending",
                        payload={},
                    )
                )
            await session.commit()

    async def _dispatch_rule_instances(
        self,
        session,
        now: datetime,
    ) -> None:
        instances = (
            await session.execute(
                select(models.NotificationInstance, models.NotificationRule)
                .join(models.NotificationRule, models.NotificationInstance.rule_id == models.NotificationRule.id)
                .where(models.NotificationInstance.status == "pending")
                .where(models.NotificationInstance.fire_at <= now)
            )
        ).all()
        if not instances:
            return
        for instance, rule in instances:
            if not rule.is_enabled:
                instance.status = "canceled"
                continue
            text = await self._build_rule_message(instance, rule)
            if not text:
                instance.status = "canceled"
                continue
            try:
                if rule.scope == "dm":
                    await self._send_rule_dm(rule, text)
                else:
                    await self._bot.send_message(
                        chat_id=rule.chat_id or self._config.main_chat_id,
                        text=text,
                        parse_mode=ParseMode.HTML,
                    )
                instance.status = "sent"
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to send rule instance %s: %s", instance.id, exc)
                instance.status = "failed"

    async def _cancel_rule_instances(self, session, event_id: str) -> None:
        await session.execute(
            update(models.NotificationInstance)
            .where(models.NotificationInstance.event_id == event_id)
            .where(models.NotificationInstance.status == "pending")
            .values(status="canceled")
        )

    async def _send_rule_dm(self, rule: models.NotificationRule, text: str) -> None:
        if not rule.user_id:
            return
        async with self._sessionmaker() as session:
            user = (
                await session.execute(
                    select(models.User).where(models.User.telegram_id == rule.user_id)
                )
            ).scalar_one_or_none()
            if not user:
                return
            prefs = normalize_user_pref(user.notify_pref)
            if not prefs.get("dm_enabled", False):
                return
            if not _is_within_dm_window(prefs, self._config.timezone):
                return
            try:
                await self._bot.send_message(
                    chat_id=user.telegram_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                )
            except TelegramForbiddenError:
                prefs["dm_enabled"] = False
                user.notify_pref = prefs
                await session.commit()
                logger.info("Disabled DM notifications for telegram_id=%s", user.telegram_id)

    async def _build_rule_message(
        self,
        instance: models.NotificationInstance,
        rule: models.NotificationRule,
    ) -> str | None:
        delay_minutes = max(0, rule.delay_seconds // 60)
        delay_text = format_duration_ru(delay_minutes) if delay_minutes else None
        description = html.escape(rule.custom_text or "")
        if rule.event_type == "war":
            war_data = await self._coc.get_current_war(self._config.clan_tag)
            current_event_id = war_data.get("tag") or war_data.get("clan", {}).get("tag")
            if instance.event_id and current_event_id != instance.event_id:
                return None
            opponent = html.escape(war_data.get("opponent", {}).get("name") or "противник")
            header = "⏰ Напоминание о войне"
            if delay_text:
                header = f"⏰ Прошло {delay_text} с начала войны против {opponent}"
            snapshot = _build_war_progress_snapshot(war_data, self._config.clan_tag)
        elif rule.event_type == "cwl":
            if not instance.event_id:
                return None
            war_data = await self._coc.get_cwl_war(instance.event_id)
            opponent = html.escape(war_data.get("opponent", {}).get("name") or "противник")
            header = "⏰ Напоминание ЛВК"
            if delay_text:
                header = f"⏰ Прошло {delay_text} с начала раунда ЛВК против {opponent}"
            snapshot = _build_war_progress_snapshot(war_data, self._config.clan_tag)
        else:
            raids = await self._coc.get_capital_raid_seasons(self._config.clan_tag)
            items = raids.get("items", [])
            if not items:
                return None
            latest = items[0]
            raid_id = latest.get("startTime") or latest.get("endTime") or "raid"
            if instance.event_id and raid_id != instance.event_id:
                return None
            header = "⏰ Напоминание по столице"
            if delay_text:
                header = f"⏰ Прошло {delay_text} с начала рейдов столицы"
            snapshot = _build_capital_snapshot(latest)
        parts = [f"<b>{header}</b>"]
        if description:
            parts.append(description)
        parts.append("")
        parts.append(snapshot)
        return "\n".join(parts)

    async def _collect_cwl_attack_summary(self) -> str | None:
        try:
            league = await self._coc.get_league_group(self._config.clan_tag)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load CWL league group for summary: %s", exc)
            return None
        totals: dict[str, dict[str, int]] = {}
        for round_item in league.get("rounds", []):
            for tag in round_item.get("warTags", []):
                if tag and tag != "#0":
                    try:
                        war_data = await self._coc.get_cwl_war(tag)
                    except Exception:  # noqa: BLE001
                        continue
                    clan, _ = _resolve_war_sides(war_data, self._config.clan_tag)
                    members = clan.get("members", [])
                    attacks_per_member = war_data.get("attacksPerMember", 2) or 2
                    for member in members:
                        name = member.get("name", "Игрок")
                        attacks = member.get("attacks", [])
                        used = len(attacks) if isinstance(attacks, list) else int(attacks or 0)
                        total_entry = totals.setdefault(name, {"used": 0, "available": 0})
                        total_entry["used"] += used
                        total_entry["available"] += attacks_per_member
        if not totals:
            return None
        rows = []
        for name, data in sorted(
            totals.items(),
            key=lambda item: (item[1]["available"] - item[1]["used"], item[0]),
            reverse=True,
        ):
            missed = data["available"] - data["used"]
            rows.append(
                {
                    "name": name,
                    "used": data["used"],
                    "available": data["available"],
                    "missed": missed,
                }
            )
        return build_total_attacks_table(rows)

    def _format_cwl_start(self, war: dict[str, Any]) -> str:
        opponent = html.escape(war.get("opponent", {}).get("name") or "противник")
        return f"<b>🏰 ЛВК: старт раунда против {opponent}!</b>"

    def _format_cwl_end(self, war: dict[str, Any]) -> str:
        clan, enemy = _resolve_war_sides(war, self._config.clan_tag)
        opponent = html.escape(enemy.get("name") or "противник")
        result = _format_war_result(clan, enemy)
        score = f"{clan.get('stars', 0)}:{enemy.get('stars', 0)}"
        text = f"<b>🏁 ЛВК против {opponent} завершён ({result}).</b>\nСчёт: {score}"
        missing_table = _build_missing_attacks_section(
            war,
            self._config.clan_tag,
            title="Кто не атаковал",
        )
        if missing_table:
            text += f"\n\n{missing_table}"
        return text

    def _format_capital_start(self, raid: dict[str, Any]) -> str:
        return "<b>🏗 Начались рейды клановой столицы!</b>"

    def _format_capital_end(self, raid: dict[str, Any]) -> str:
        snapshot = _build_capital_snapshot(raid)
        return f"<b>🏁 Рейд-уикенд завершён.</b>\n\n{snapshot}"

    async def _send_event(self, text: str, notify_type: str) -> None:
        await self._send_chat_notification(text, notify_type)
        await self._send_dm_notifications(text, notify_type)

    async def _send_reminder_dm(self, reminder: models.ScheduledNotification, text: str) -> None:
        target_id = reminder.context.get("target_user_id")
        if not target_id:
            return
        async with self._sessionmaker() as session:
            user = (
                await session.execute(
                    select(models.User).where(models.User.telegram_id == target_id)
                )
            ).scalar_one_or_none()
            if not user:
                return
            prefs = normalize_user_pref(user.notify_pref)
            if not prefs.get("dm_enabled", False):
                return
            category = EVENT_CATEGORY_MAP.get(reminder.event_type, (None, None))[0]
            if category and not prefs.get("dm_categories", {}).get(category, False):
                return
            if not _is_within_dm_window(prefs, self._config.timezone):
                return
            try:
                await self._bot.send_message(
                    chat_id=user.telegram_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                )
            except TelegramForbiddenError:
                prefs["dm_enabled"] = False
                user.notify_pref = prefs
                await session.commit()
                logger.info("Disabled DM notifications for telegram_id=%s", user.telegram_id)

    async def _send_chat_notification(self, text: str, notify_type: str) -> None:
        if await self._chat_type_enabled(notify_type):
            await self._bot.send_message(
                chat_id=self._config.main_chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
            )

    async def send_test_notification(self, notify_type: str) -> None:
        samples = {
            "war_preparation": "<b>🧪 Тест КВ: подготовка.</b>",
            "war_start": "<b>🧪 Тест КВ: старт войны.</b>",
            "war_end": "<b>🧪 Тест КВ: итоги.</b>",
            "cwl_round_start": "<b>🧪 Тест ЛВК: старт раунда.</b>",
            "cwl_round_end": "<b>🧪 Тест ЛВК: конец раунда.</b>",
            "capital_start": "<b>🧪 Тест столицы: старт рейдов.</b>",
            "capital_end": "<b>🧪 Тест столицы: итоги рейдов.</b>",
        }
        text = samples.get(notify_type)
        if not text:
            return
        await self._send_event(text, notify_type)

    async def _send_dm_notifications(self, text: str, notify_type: str) -> None:
        async with self._sessionmaker() as session:
            users = (await session.execute(select(models.User))).scalars().all()
            for user in users:
                prefs = normalize_user_pref(user.notify_pref)
                if not prefs.get("dm_enabled", False):
                    continue
                category = EVENT_CATEGORY_MAP.get(notify_type, (None, None))[0]
                if category and not prefs.get("dm_categories", {}).get(category, False):
                    continue
                if not _is_within_dm_window(prefs, self._config.timezone):
                    continue
                try:
                    await self._bot.send_message(
                        chat_id=user.telegram_id,
                        text=text,
                        parse_mode=ParseMode.HTML,
                    )
                except TelegramForbiddenError:
                    prefs["dm_enabled"] = False
                    user.notify_pref = prefs
                    await session.commit()
                    logger.info("Disabled DM notifications for telegram_id=%s", user.telegram_id)

    async def _chat_type_enabled(self, notify_type: str) -> bool:
        category_key = EVENT_CATEGORY_MAP.get(notify_type)
        if not category_key:
            return False
        category, key = category_key
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
                    chat_id=self._config.main_chat_id, preferences=DEFAULT_CHAT_PREFS
                )
                session.add(settings)
                await session.commit()
                return DEFAULT_CHAT_PREFS.get(category, {}).get(key, True)
            prefs = normalize_chat_prefs(settings.preferences)
            return bool(prefs.get(category, {}).get(key, True))


def normalize_chat_prefs(pref: dict | None) -> dict:
    pref = dict(pref or {})
    merged: dict[str, dict[str, bool]] = {}
    for category, defaults in DEFAULT_CHAT_PREFS.items():
        cat_pref = dict(defaults)
        cat_pref.update(pref.get(category, {}) or {})
        merged[category] = cat_pref
    return merged


def normalize_user_pref(pref: dict | None) -> dict[str, Any]:
    pref = dict(pref or {})
    pref.setdefault("dm_enabled", False)
    pref.setdefault("dm_window", "always")
    categories = dict(DEFAULT_DM_CATEGORIES)
    legacy_types = pref.get("dm_types", {}) or {}
    if any(legacy_types.get(key, False) for key in ("preparation", "inWar", "warEnded")):
        categories["war"] = True
    if legacy_types.get("cwlEnded", False):
        categories["cwl"] = True
    categories.update(pref.get("dm_categories", {}) or {})
    pref["dm_categories"] = categories
    return pref


def _is_within_dm_window(pref: dict[str, Any], tz_name: str) -> bool:
    if pref.get("dm_window") == "always":
        return True
    zone = ZoneInfo(tz_name)
    now_local = datetime.now(zone)
    start = now_local.replace(hour=8, minute=0, second=0, microsecond=0)
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


def _resolve_war_sides(war_data: dict[str, Any], clan_tag: str) -> tuple[dict[str, Any], dict[str, Any]]:
    clan = war_data.get("clan", {})
    opponent = war_data.get("opponent", {})
    if clan_tag:
        normalized = clan_tag.upper()
        if opponent.get("tag", "").upper() == normalized and clan.get("tag", "").upper() != normalized:
            return opponent, clan
    return clan, opponent


def _build_missing_attacks_section(
    war_data: dict[str, Any],
    clan_tag: str,
    title: str,
) -> str | None:
    clan, _ = _resolve_war_sides(war_data, clan_tag)
    missed = collect_missed_attacks({**war_data, "clan": clan})
    if not missed:
        return None
    table = build_missed_attacks_table(missed)
    return f"{title}:\n{table}"


def _build_war_progress_snapshot(war_data: dict[str, Any], clan_tag: str) -> str:
    clan, opponent = _resolve_war_sides(war_data, clan_tag)
    clan_stars = clan.get("stars", 0)
    enemy_stars = opponent.get("stars", 0)
    clan_destr = clan.get("destructionPercentage", 0)
    enemy_destr = opponent.get("destructionPercentage", 0)
    attacks_per_member = war_data.get("attacksPerMember", 2) or 2
    members = clan.get("members", [])
    attacks_used = clan.get("attacks")
    if attacks_used is None:
        attacks_used = sum(len(member.get("attacks", [])) for member in members)
    total_attacks = attacks_per_member * len(members)
    missed = collect_missed_attacks({**war_data, "clan": clan})
    lines = [
        "<b>Состояние сейчас</b>",
        f"⭐ Наши/их звёзды: {clan_stars} / {enemy_stars}",
        f"💥 Разрушение: {clan_destr}% / {enemy_destr}%",
        f"⚔️ Атаки: {attacks_used}/{total_attacks}",
    ]
    if missed:
        lines.append("Кто не атаковал:")
        lines.append(build_missed_attacks_table(missed))
    else:
        lines.append("Все атаки сделаны.")
    return "\n".join(lines)


def _format_top_list(title: str, items: list[tuple[str, int]]) -> str:
    if not items:
        return f"{title}: нет данных."
    lines = [f"<b>{html.escape(title)}</b>"]
    for index, (name, value) in enumerate(items, start=1):
        safe_name = html.escape(name)
        lines.append(f"{index}. {safe_name} — {value}")
    return "\n".join(lines)


def _build_war_snapshot(war_data: dict[str, Any]) -> str:
    clan, opponent = _resolve_war_sides(war_data, war_data.get("clan", {}).get("tag") or "")
    clan_stars = clan.get("stars", 0)
    enemy_stars = opponent.get("stars", 0)
    clan_destr = clan.get("destructionPercentage", 0)
    enemy_destr = opponent.get("destructionPercentage", 0)
    attacks_per_member = war_data.get("attacksPerMember", 2) or 2
    members = clan.get("members", [])
    attacks_used = clan.get("attacks")
    if attacks_used is None:
        attacks_used = sum(len(member.get("attacks", [])) for member in members)
    total_attacks = attacks_per_member * len(members)
    missing = []
    for member in members:
        used = len(member.get("attacks", []))
        remaining = attacks_per_member - used
        if remaining > 0:
            name = html.escape(member.get("name", "Игрок"))
            missing.append(f"{name} ({remaining})")
    lines = [
        "<b>Состояние сейчас</b>",
        f"⭐ Наши/их звёзды: {clan_stars} / {enemy_stars}",
        f"💥 Разрушение: {clan_destr}% / {enemy_destr}%",
        f"⚔️ Атаки: {attacks_used}/{total_attacks}",
    ]
    if missing:
        lines.append("Не атаковали:")
        lines.append("<pre>{}</pre>".format("\n".join(missing)))
    else:
        lines.append("Все атаки сделаны.")
    return "\n".join(lines)


def _build_capital_snapshot(raid: dict[str, Any]) -> str:
    members = raid.get("members", [])
    total_attacks = sum(member.get("attackLimit", 0) for member in members)
    attacks_used = sum(member.get("attacks", 0) for member in members)
    total_loot = raid.get("capitalTotalLoot", raid.get("totalLoot", 0))
    missing = []
    for member in members:
        limit = member.get("attackLimit", 0)
        used = member.get("attacks", 0)
        remaining = limit - used
        if remaining > 0:
            name = html.escape(member.get("name", "Игрок"))
            missing.append(f"{name} ({remaining})")
    lines = [
        "<b>Состояние сейчас</b>",
        f"⚔️ Атаки: {attacks_used}/{total_attacks}",
        f"💰 Лут столицы: {total_loot}",
    ]
    if missing:
        lines.append("Не добили атаки:")
        lines.append("<pre>{}</pre>".format("\n".join(missing)))
    else:
        lines.append("Все атаки сделаны.")
    return "\n".join(lines)
