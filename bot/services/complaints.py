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
from bot.ui.renderers import chunk_message

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
        lines.append(
            f"<b>Кто:</b> {created_by_name} <code>{complaint.created_by_tg_id}</code>"
        )
    else:
        lines.append(f"<b>Источник:</b> {created_by_name}")
    target_tag_text = f"<code>{target_tag}</code>" if target_tag else ""
    lines.append(f"<b>На кого:</b> {target_name} {target_tag_text}".strip())
    lines.append(f"<b>Дата:</b> {created_at}")
    lines.append("<b>Текст:</b>")
    if message_text:
        for entry in message_text.splitlines():
            lines.append(f"• {entry}" if entry.strip() else "• —")
    else:
        lines.append("• —")
    return "\n".join(lines)


async def notify_admins_complaint(
    bot: Bot,
    config: BotConfig,
    complaint: models.Complaint,
) -> None:
    text = build_complaint_message(complaint, config.timezone)
    markup = complaint_admin_kb(complaint.id)
    dm_count = 0
    for admin_id in config.admin_telegram_ids:
        try:
            for index, chunk in enumerate(chunk_message(text)):
                await bot.send_message(
                    chat_id=admin_id,
                    text=chunk,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup if index == 0 else None,
                )
            dm_count += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to send complaint %s to admin %s: %s", complaint.id, admin_id, exc)
    admin_chat_used = False
    if config.admin_chat_id and config.admin_chat_id != config.main_chat_id:
        try:
            for index, chunk in enumerate(chunk_message(text)):
                await bot.send_message(
                    chat_id=config.admin_chat_id,
                    text=chunk,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup if index == 0 else None,
                )
            admin_chat_used = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to send complaint %s to admin chat %s: %s",
                complaint.id,
                config.admin_chat_id,
                exc,
            )
    logger.info(
        "Complaint sent to admins: dm_count=%s admin_chat_used=%s",
        dm_count,
        admin_chat_used,
    )
