from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.services.stats_collector import StatsCollector


def configure_scheduler(collector: StatsCollector) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(collector.collect_daily_snapshots, "interval", hours=6, id="daily_snapshots")
    scheduler.add_job(collector.refresh_current_war, "interval", minutes=10, id="war_refresh")
    return scheduler
