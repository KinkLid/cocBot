from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class BotConfig:
    bot_token: str
    coc_api_token: str
    clan_tag: str
    main_chat_id: int
    admin_telegram_ids: set[int]
    timezone: str
    database_url: str
    log_level: str = "INFO"
    default_notify_channel: str = "dm"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_config() -> BotConfig:
    config_path = Path(os.getenv("BOT_CONFIG", "config.yml"))
    data = _load_yaml(config_path)

    env = os.environ
    bot_token = env.get("BOT_TOKEN", data.get("bot_token"))
    coc_api_token = env.get("COC_API_TOKEN", data.get("coc_api_token"))
    clan_tag = env.get("CLAN_TAG", data.get("clan_tag"))
    main_chat_id = env.get("MAIN_CHAT_ID", data.get("main_chat_id"))
    admin_ids = env.get("ADMIN_TELEGRAM_IDS", data.get("admin_telegram_ids", []))
    timezone = env.get("TIMEZONE", data.get("timezone", "Europe/Moscow"))
    database_url = env.get("DATABASE_URL", data.get("database_url"))
    log_level = env.get("LOG_LEVEL", data.get("log_level", "INFO"))
    default_notify_channel = env.get(
        "DEFAULT_NOTIFY_CHANNEL", data.get("default_notify_channel", "dm")
    )

    if not bot_token:
        raise RuntimeError("BOT_TOKEN is required")
    if not coc_api_token:
        raise RuntimeError("COC_API_TOKEN is required")
    if not clan_tag:
        raise RuntimeError("CLAN_TAG is required")
    if main_chat_id is None:
        raise RuntimeError("MAIN_CHAT_ID is required")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")

    if isinstance(admin_ids, str):
        admin_ids = {int(x) for x in admin_ids.split(",") if x.strip()}
    else:
        admin_ids = {int(x) for x in admin_ids}

    return BotConfig(
        bot_token=str(bot_token),
        coc_api_token=str(coc_api_token),
        clan_tag=str(clan_tag).upper(),
        main_chat_id=int(main_chat_id),
        admin_telegram_ids=admin_ids,
        timezone=str(timezone),
        database_url=str(database_url),
        log_level=str(log_level),
        default_notify_channel=str(default_notify_channel),
    )
