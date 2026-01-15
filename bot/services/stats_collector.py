from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.db import models
from bot.services.coc_client import CocClient

logger = logging.getLogger(__name__)


class StatsCollector:
    def __init__(self, sessionmaker: async_sessionmaker, coc_client: CocClient, clan_tag: str) -> None:
        self._sessionmaker = sessionmaker
        self._coc = coc_client
        self._clan_tag = clan_tag

    async def collect_daily_snapshots(self) -> None:
        async with self._sessionmaker() as session:
            users = (await session.execute(select(models.User))).scalars().all()
            for user in users:
                try:
                    data = await self._coc.get_player(user.player_tag)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to load player %s: %s", user.player_tag, exc)
                    continue
                payload: dict[str, Any] = {
                    "trophies": data.get("trophies"),
                    "donations": data.get("donations"),
                    "donations_received": data.get("donationsReceived"),
                    "war_stars": data.get("warStars"),
                    "attack_wins": data.get("attackWins"),
                    "defense_wins": data.get("defenseWins"),
                }
                session.add(
                    models.StatsDaily(
                        telegram_id=user.telegram_id,
                        captured_at=datetime.utcnow(),
                        payload=payload,
                    )
                )
            await session.commit()

    async def refresh_current_war(self) -> None:
        try:
            war_data = await self._coc.get_current_war(self._clan_tag)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load current war: %s", exc)
            return

        war_tag = war_data.get("tag") or war_data.get("clan", {}).get("tag")
        async with self._sessionmaker() as session:
            existing = None
            if war_tag:
                existing = (
                    await session.execute(select(models.War).where(models.War.war_tag == war_tag))
                ).scalar_one_or_none()
            if existing is None:
                existing = models.War(
                    war_tag=war_tag,
                    war_type=war_data.get("warType", "unknown"),
                    state=war_data.get("state", "unknown"),
                    start_at=None,
                    end_at=None,
                    opponent_name=war_data.get("opponent", {}).get("name"),
                    opponent_tag=war_data.get("opponent", {}).get("tag"),
                    league_name=war_data.get("league", {}).get("name"),
                )
                session.add(existing)
            else:
                existing.state = war_data.get("state", existing.state)
            await session.commit()
