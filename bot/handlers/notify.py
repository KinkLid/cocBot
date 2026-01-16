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
from bot.keyboards.common import main_menu_reply, notify_category_reply, notify_menu_reply
from bot.services.permissions import is_admin
from bot.utils.navigation import pop_menu, reset_menu, set_menu
from bot.utils.state import reset_state_if_any

router = Router()

DEFAULT_DM_CATEGORIES = {
    "war": False,
    "cwl": False,
    "capital": False,
}


def _normalize_notify_pref(pref: dict | None) -> dict:
    pref = dict(pref or {})
    dm_enabled = bool(pref.get("dm_enabled", False))
    dm_window = pref.get("dm_window", "always")
    categories = dict(DEFAULT_DM_CATEGORIES)
    legacy_types = pref.get("dm_types", {}) or {}
    if legacy_types:
        if any(legacy_types.get(key, False) for key in ("preparation", "inWar", "warEnded")):
            categories["war"] = True
        if legacy_types.get("cwlEnded", False):
            categories["cwl"] = True
    categories.update(pref.get("dm_categories", {}) or {})
    return {
        "dm_enabled": dm_enabled,
        "dm_window": dm_window,
        "dm_categories": categories,
    }


@router.message(Command("notify"))
async def notify_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    await reset_menu(state)
    await set_menu(state, "notify_menu")
    await state.update_data(notify_category=None)
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
        f"ЛС: {'✅ включены' if dm_enabled else '⛔ выключены'}. Выберите раздел.",
        reply_markup=notify_menu_reply(dm_enabled, prefs["dm_window"]),
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
                reply_markup=notify_menu_reply(dm_enabled, prefs["dm_window"]),
            )
            return
        elif not dm_enabled and message.text == "Выключить ЛС":
            await message.answer(
                "ЛС уже выключены.",
                reply_markup=notify_menu_reply(dm_enabled, prefs["dm_window"]),
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
                reply_markup=notify_menu_reply(False, prefs["dm_window"]),
            )
            return
        await message.answer(
            "Готово! ЛС включены.",
            reply_markup=notify_menu_reply(True, prefs["dm_window"]),
        )
        return
    await message.answer(
        "Готово! ЛС выключены.",
        reply_markup=notify_menu_reply(False, prefs["dm_window"]),
    )


@router.message(F.text.in_({"ЛС: ✅ включены", "ЛС: ⛔ выключены"}))
async def notify_status_button(message: Message) -> None:
    await message.answer("Состояние уже выбрано.")

@router.message(F.text.in_({"Клановые войны", "ЛВК", "Рейды столицы"}))
async def notify_category_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    category_map = {
        "Клановые войны": ("war", "Клановые войны"),
        "ЛВК": ("cwl", "ЛВК"),
        "Рейды столицы": ("capital", "Рейды столицы"),
    }
    category, label = category_map.get(message.text, (None, None))
    if not category:
        return
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
    await set_menu(state, f"notify_{category}")
    await state.update_data(notify_category=category)
    await message.answer(
        f"{label}: настройки ЛС.",
        reply_markup=notify_category_reply(
            label,
            bool(prefs.get("dm_enabled", False)),
            bool(prefs.get("dm_categories", {}).get(category, False)),
        ),
    )


@router.message(F.text.in_({"Включить ЛС для раздела", "Отключить ЛС для раздела"}))
async def notify_category_toggle(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    data = await state.get_data()
    category = data.get("notify_category")
    if category not in {"war", "cwl", "capital"}:
        await notify_command(message, state, config, sessionmaker)
        return
    category_labels = {"war": "Клановые войны", "cwl": "ЛВК", "capital": "Рейды столицы"}
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
        current = bool(prefs["dm_categories"].get(category, False))
        new_state = not current if message.text == "Включить ЛС для раздела" else False
        prefs["dm_categories"][category] = new_state
        user.notify_pref = prefs
        await session.commit()
    await message.answer(
        "Настройка сохранена.",
        reply_markup=notify_category_reply(
            category_labels[category],
            bool(prefs.get("dm_enabled", False)),
            bool(prefs.get("dm_categories", {}).get(category, False)),
        ),
    )


@router.message(F.text == "Назад к уведомлениям")
async def notify_back(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    await pop_menu(state)
    await notify_command(message, state, config, sessionmaker)


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
            prefs["dm_window"],
        ),
    )
