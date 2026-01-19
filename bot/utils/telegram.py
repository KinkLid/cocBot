from __future__ import annotations

from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_bot_dm_link(bot_username: str, start_param: str | None = None) -> str:
    if start_param:
        return f"https://t.me/{bot_username}?start={start_param}"
    return f"https://t.me/{bot_username}"


def build_bot_dm_keyboard(
    bot_username: str,
    label: str = "Открыть бота",
    start_param: str | None = None,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    url=build_bot_dm_link(bot_username, start_param=start_param),
                )
            ]
        ]
    )


async def try_send_dm(bot, user_id: int, text: str, reply_markup=None, parse_mode=None) -> bool:
    try:
        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except TelegramForbiddenError:
        return False
    return True
