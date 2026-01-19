from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data == "hint:ok")
async def hint_ok(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        await callback.message.delete()
    except TelegramBadRequest as exc:
        logger.info("Failed to delete hint message: %s", exc)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest as exc2:
            logger.info("Failed to edit hint message: %s", exc2)
