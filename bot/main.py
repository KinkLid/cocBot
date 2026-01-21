from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import load_config
from bot.db import build_engine, build_sessionmaker
from bot.handlers import admin, common, complaints, hints, notify, registration, stats, targets
from bot.jobs.scheduler import configure_scheduler
from bot.services.commands import register_bot_commands
from bot.services.coc_client import CocClient
from bot.services.guards import ClanAccessMiddleware
from bot.services.notifications import NotificationService
from bot.services.stats_collector import StatsCollector


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


async def main() -> None:
    config = load_config()
    setup_logging(config.log_level)

    bot = Bot(token=config.bot_token)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    engine = build_engine(config.database_url)
    sessionmaker = build_sessionmaker(engine)
    coc_client = CocClient(base_url="https://api.clashofclans.com/v1", token=config.coc_api_token)
    stats_collector = StatsCollector(sessionmaker, coc_client, config.clan_tag)
    notifier = NotificationService(bot, config, sessionmaker, coc_client)
    scheduler = configure_scheduler(stats_collector, notifier)

    dp["config"] = config
    dp["sessionmaker"] = sessionmaker
    dp["coc_client"] = coc_client

    me = await bot.get_me()
    dp["bot_username"] = me.username
    await register_bot_commands(bot)

    guard_middleware = ClanAccessMiddleware(config, sessionmaker, coc_client)
    dp.message.middleware(guard_middleware)
    dp.callback_query.middleware(guard_middleware)

    dp.include_router(common.router)
    dp.include_router(complaints.router)
    dp.include_router(hints.router)
    dp.include_router(registration.router)
    dp.include_router(stats.router)
    dp.include_router(notify.router)
    dp.include_router(targets.router)
    dp.include_router(admin.router)

    scheduler.start()
    logging.getLogger(__name__).info("Notification scheduler started")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
