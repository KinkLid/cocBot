from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import main_menu_reply, notify_menu_reply
from bot.services.permissions import is_admin
from bot.utils.state import reset_state_if_any

router = Router()

DEFAULT_DM_TYPES = {
    "preparation": True,
    "inWar": True,
    "warEnded": True,
    "cwlEnded": False,
}


def _normalize_notify_pref(pref: dict | None) -> dict:
    pref = dict(pref or {})
    pref.setdefault("dm_enabled", False)
    types = dict(DEFAULT_DM_TYPES)
    types.update(pref.get("dm_types", {}) or {})
    pref["dm_types"] = types
    pref.setdefault("dm_window", "always")
    return pref


@router.message(Command("notify"))
async def notify_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    async with sessionmaker() as session:
        user = (
            await session.execute(select(models.User).where(models.User.telegram_id == message.from_user.id))
        ).scalar_one_or_none()
        if not user:
            await message.answer(
                "Вы ещё не зарегистрированы. Нажмите «Регистрация».",
                reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
            )
            return
        prefs = _normalize_notify_pref(user.notify_pref)
        dm_enabled = bool(prefs.get("dm_enabled", False))
    await message.answer(
        f"ЛС: {'✅ включены' if dm_enabled else '⛔ выключены'}. Настройте типы и время.",
        reply_markup=notify_menu_reply(dm_enabled, prefs["dm_types"], prefs["dm_window"]),
    )


@router.message(F.text == "Настройки уведомлений")
async def notify_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await notify_command(message, state, config, sessionmaker)


@router.message(F.text.in_({"Включить ЛС", "Выключить ЛС"}))
async def notify_toggle_dm_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    async with sessionmaker() as session:
        user = (
            await session.execute(
                select(models.User).where(models.User.telegram_id == message.from_user.id)
            )
        ).scalar_one_or_none()
        if not user:
            await message.answer(
                "Вы ещё не зарегистрированы. Нажмите «Регистрация».",
                reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
            )
            return
        prefs = _normalize_notify_pref(user.notify_pref)
        dm_enabled = bool(prefs.get("dm_enabled", False))
        new_state = not dm_enabled if message.text == "Включить ЛС" else False
        if dm_enabled and message.text == "Выключить ЛС":
            new_state = False
        elif not dm_enabled and message.text == "Включить ЛС":
            new_state = True
        elif dm_enabled and message.text == "Включить ЛС":
            await message.answer(
                "ЛС уже включены.",
                reply_markup=notify_menu_reply(dm_enabled, prefs["dm_types"], prefs["dm_window"]),
            )
            return
        elif not dm_enabled and message.text == "Выключить ЛС":
            await message.answer(
                "ЛС уже выключены.",
                reply_markup=notify_menu_reply(dm_enabled, prefs["dm_types"], prefs["dm_window"]),
            )
            return
        prefs["dm_enabled"] = new_state
        user.notify_pref = prefs
        await session.commit()
    if new_state:
        try:
            await message.bot.send_message(
                chat_id=message.from_user.id,
                text="Проверка: уведомления будут приходить в ЛС.",
            )
        except TelegramForbiddenError:
            prefs = dict(prefs)
            prefs["dm_enabled"] = False
            async with sessionmaker() as session:
                user = (
                    await session.execute(
                        select(models.User).where(models.User.telegram_id == message.from_user.id)
                    )
                ).scalar_one_or_none()
                if user:
                    user.notify_pref = prefs
                    await session.commit()
            await message.answer(
                "Не могу писать в ЛС. Откройте ЛС и включите снова.",
                reply_markup=notify_menu_reply(False, prefs["dm_types"], prefs["dm_window"]),
            )
            return
        await message.answer(
            "Готово! ЛС включены.",
            reply_markup=notify_menu_reply(True, prefs["dm_types"], prefs["dm_window"]),
        )
        return
    await message.answer(
        "Готово! ЛС выключены.",
        reply_markup=notify_menu_reply(False, prefs["dm_types"], prefs["dm_window"]),
    )


@router.message(F.text.in_({"✅ ЛС включены", "⛔ ЛС выключены"}))
async def notify_status_button(message: Message) -> None:
    await message.answer("Состояние уже выбрано.")


@router.message(F.text.startswith("W1 подготовка"))
@router.message(F.text.startswith("W2 война"))
@router.message(F.text.startswith("W3 итог"))
@router.message(F.text.startswith("W4 ЛВК"))
async def notify_dm_type_toggle(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    async with sessionmaker() as session:
        user = (
            await session.execute(select(models.User).where(models.User.telegram_id == message.from_user.id))
        ).scalar_one_or_none()
        if not user:
            await message.answer(
                "Вы ещё не зарегистрированы. Нажмите «Регистрация».",
                reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
            )
            return
        prefs = _normalize_notify_pref(user.notify_pref)
        label = message.text.split(":")[0].strip()
        mapping = {
            "W1 подготовка": "preparation",
            "W2 война": "inWar",
            "W3 итог": "warEnded",
            "W4 ЛВК": "cwlEnded",
        }
        key = mapping.get(label)
        if not key:
            await message.answer("Неизвестный тип.")
            return
        prefs["dm_types"][key] = not prefs["dm_types"].get(key, False)
        user.notify_pref = prefs
        await session.commit()
    await message.answer(
        "Тип уведомлений обновлён.",
        reply_markup=notify_menu_reply(
            bool(prefs.get("dm_enabled", False)),
            prefs["dm_types"],
            prefs["dm_window"],
        ),
    )


@router.message(F.text.startswith("Время ЛС:"))
async def notify_dm_window_toggle(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    async with sessionmaker() as session:
        user = (
            await session.execute(select(models.User).where(models.User.telegram_id == message.from_user.id))
        ).scalar_one_or_none()
        if not user:
            await message.answer(
                "Вы ещё не зарегистрированы. Нажмите «Регистрация».",
                reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
            )
            return
        prefs = _normalize_notify_pref(user.notify_pref)
        prefs["dm_window"] = "day" if prefs.get("dm_window") == "always" else "always"
        user.notify_pref = prefs
        await session.commit()
    await message.answer(
        "Окно доставки обновлено.",
        reply_markup=notify_menu_reply(
            bool(prefs.get("dm_enabled", False)),
            prefs["dm_types"],
            prefs["dm_window"],
        ),
    )
