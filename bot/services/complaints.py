from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.enums import ParseMode

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.complaints import complaint_admin_kb

logger = logging.getLogger(__name__)


def _format_datetime(value: datetime | None, zone: ZoneInfo) -> str:
    if not value:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(zone).strftime("%Y-%m-%d %H:%M")


def build_complaint_message(complaint: models.Complaint, timezone_name: str) -> str:
    zone = ZoneInfo(timezone_name)
    created_at = _format_datetime(complaint.created_at, zone)
    target_name = html.escape(complaint.target_player_name or "Игрок")
    target_tag = html.escape(complaint.target_player_tag or "")
    message_text = html.escape(complaint.text or "")
    created_by_name = html.escape(complaint.created_by_tg_name or "Авто-предупреждение")
    header = "📣 Жалоба" if complaint.type == "user" else "⚠️ Предупреждение"

    lines = [f"<b>{header}</b>"]
    if complaint.created_by_tg_id:
        lines.append(f"Кто пожаловался: {created_by_name} (ID {complaint.created_by_tg_id})")
    else:
        lines.append(f"Источник: {created_by_name}")
    lines.append(f"На кого: {target_name} ({target_tag})")
    lines.append(f"Дата: {created_at}")
    if message_text:
        lines.append("Текст:")
        lines.append(f"<pre>{message_text}</pre>")
    else:
        lines.append("Текст: —")
    return "\n".join(lines)


async def notify_admins_about_complaint(
    bot: Bot,
    config: BotConfig,
    complaint: models.Complaint,
) -> None:
    text = build_complaint_message(complaint, config.timezone)
    markup = complaint_admin_kb(complaint.id)
    try:
        await bot.send_message(
            chat_id=config.main_chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to send complaint %s to main chat: %s", complaint.id, exc)
    for admin_id in config.admin_telegram_ids:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to send complaint %s to admin %s: %s", complaint.id, admin_id, exc)
