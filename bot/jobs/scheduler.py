from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.services.notifications import NotificationService
from bot.services.stats_collector import StatsCollector


def configure_scheduler(collector: StatsCollector, notifier: NotificationService) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(collector.collect_daily_snapshots, "interval", hours=6, id="daily_snapshots")
    scheduler.add_job(notifier.poll_war_state, "interval", seconds=90, id="war_state_poll")
    scheduler.add_job(notifier.poll_cwl_state, "interval", minutes=10, id="cwl_state_poll")
    scheduler.add_job(notifier.poll_capital_state, "interval", minutes=15, id="capital_state_poll")
    scheduler.add_job(notifier.poll_clan_members, "interval", minutes=5, id="clan_members_poll")
    scheduler.add_job(
        notifier.dispatch_scheduled_notifications, "interval", seconds=60, id="scheduled_notifications"
    )
    return scheduler
