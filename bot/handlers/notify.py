from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import main_menu_reply, notify_menu_reply
from bot.services.coc_client import CocClient
from bot.services.permissions import is_admin
from bot.utils.coc_time import parse_coc_time
from bot.utils.navigation import pop_menu, reset_menu, set_menu
from bot.utils.notify_time import format_duration_ru, parse_delay_to_minutes
from bot.utils.state import reset_state_if_any

router = Router()

DEFAULT_DM_CATEGORIES = {
    "war": False,
    "cwl": False,
    "capital": False,
}


class NotifyState(StatesGroup):
    reminder_delay_value = State()
    reminder_text = State()


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
        "Настройки уведомлений.",
        reply_markup=notify_menu_reply(dm_enabled, prefs["dm_window"], prefs["dm_categories"]),
    )


@router.message(F.text == "Настройки уведомлений")
async def notify_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await notify_command(message, state, config, sessionmaker)


@router.message(
    F.text.startswith("🟢 Личные уведомления") | F.text.startswith("🔴 Личные уведомления")
)
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
        prefs["dm_enabled"] = not dm_enabled
        user.notify_pref = prefs
        await session.commit()
    if prefs["dm_enabled"]:
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
                reply_markup=notify_menu_reply(False, prefs["dm_window"], prefs["dm_categories"]),
            )
            return
        await message.answer(
            "Готово! ЛС включены.",
            reply_markup=notify_menu_reply(True, prefs["dm_window"], prefs["dm_categories"]),
        )
        return
    await message.answer(
        "Готово! ЛС выключены.",
        reply_markup=notify_menu_reply(False, prefs["dm_window"], prefs["dm_categories"]),
    )


@router.message(
    F.text.startswith("✅ КВ уведомления")
    | F.text.startswith("☑️ КВ уведомления")
    | F.text.startswith("✅ ЛВК уведомления")
    | F.text.startswith("☑️ ЛВК уведомления")
    | F.text.startswith("✅ Рейды уведомления")
    | F.text.startswith("☑️ Рейды уведомления")
)
async def notify_category_toggle(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    text = message.text or ""
    category_map = {
        "КВ уведомления": "war",
        "ЛВК уведомления": "cwl",
        "Рейды уведомления": "capital",
    }
    category = None
    for label, key in category_map.items():
        if label in text:
            category = key
            break
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
        current = bool(prefs["dm_categories"].get(category, False))
        prefs["dm_categories"][category] = not current
        user.notify_pref = prefs
        await session.commit()
    await message.answer(
        "Настройка сохранена.",
        reply_markup=notify_menu_reply(
            bool(prefs.get("dm_enabled", False)),
            prefs["dm_window"],
            prefs["dm_categories"],
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


@router.message(F.text.startswith("Режим ЛС:"))
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
        "Режим доставки обновлён. В режиме «только днём» уведомления приходят с 8:00 до 22:00.",
        reply_markup=notify_menu_reply(
            bool(prefs.get("dm_enabled", False)),
            prefs["dm_window"],
            prefs["dm_categories"],
        ),
    )


@router.message(F.text.in_({"➕ Напоминание КВ", "➕ Напоминание ЛВК", "➕ Напоминание рейдов"}))
async def notify_create_reminder(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    category_map = {
        "➕ Напоминание КВ": "war",
        "➕ Напоминание ЛВК": "cwl",
        "➕ Напоминание рейдов": "capital",
    }
    category = category_map.get(message.text)
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
        if not prefs.get("dm_enabled", False):
            await message.answer(
                "Сначала включите личные уведомления.",
                reply_markup=notify_menu_reply(False, prefs["dm_window"], prefs["dm_categories"]),
            )
            return
    await state.update_data(reminder_category=category)
    await state.set_state(NotifyState.reminder_delay_value)
    await message.answer(
        "Введите время через которое прислать напоминание от начала события "
        "(например, 22h для 22 часов или 30m для 30 минут)."
    )


@router.message(NotifyState.reminder_delay_value)
async def notify_reminder_delay_value(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    if message.text == "Главное меню":
        await reset_state_if_any(state)
        await reset_menu(state)
        await message.answer(
            "Главное меню.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    value = parse_delay_to_minutes(message.text or "")
    if not value:
        await message.answer(
            "Нужно указать время в формате 22h или 30m.",
        )
        return
    await state.update_data(reminder_delay=value)
    await state.set_state(NotifyState.reminder_text)
    await message.answer(
        "Введите текст напоминания или отправьте '-' чтобы оставить только шаблон."
    )


@router.message(NotifyState.reminder_text)
async def notify_reminder_text(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    text = (message.text or "").strip()
    if text == "Главное меню":
        await reset_state_if_any(state)
        await reset_menu(state)
        await message.answer(
            "Главное меню.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    reminder_text = "" if text == "-" else text
    data = await state.get_data()
    category = data.get("reminder_category")
    delay_minutes = data.get("reminder_delay")
    if category not in {"war", "cwl", "capital"} or not delay_minutes:
        await state.clear()
        await message.answer("Не удалось создать напоминание.")
        return

    context: dict = {"scope": "dm", "target_user_id": message.from_user.id, "delay_minutes": delay_minutes}
    start_at = None
    event_type = None
    if category == "war":
        try:
            war_data = await coc_client.get_current_war(config.clan_tag)
        except Exception as exc:  # noqa: BLE001
            await state.clear()
            await message.answer(f"Не удалось получить данные о войне: {exc}")
            return
        if war_data.get("state") not in {"preparation", "inWar"}:
            await state.clear()
            await message.answer("Сейчас нет активной войны.")
            return
        war_tag = war_data.get("tag") or war_data.get("clan", {}).get("tag")
        context["war_tag"] = war_tag
        start_at = parse_coc_time(war_data.get("startTime"))
        event_type = "war_reminder"
    elif category == "cwl":
        try:
            league = await coc_client.get_league_group(config.clan_tag)
        except Exception as exc:  # noqa: BLE001
            await state.clear()
            await message.answer(f"Не удалось получить данные ЛВК: {exc}")
            return
        war_tag = None
        war_data = None
        for round_item in league.get("rounds", []):
            for tag in round_item.get("warTags", []):
                if tag and tag != "#0":
                    try:
                        war_data = await coc_client.get_cwl_war(tag)
                    except Exception:  # noqa: BLE001
                        continue
                    if war_data and war_data.get("state") in {"preparation", "inWar"}:
                        war_tag = tag
                        break
            if war_tag:
                break
        if not war_tag or not war_data:
            await state.clear()
            await message.answer("Нет активного раунда ЛВК.")
            return
        context["cwl_war_tag"] = war_tag
        context["season"] = league.get("season")
        start_at = parse_coc_time(war_data.get("startTime"))
        event_type = "cwl_reminder"
    else:
        try:
            raids = await coc_client.get_capital_raid_seasons(config.clan_tag)
        except Exception as exc:  # noqa: BLE001
            await state.clear()
            await message.answer(f"Не удалось получить рейды столицы: {exc}")
            return
        items = raids.get("items", [])
        if not items:
            await state.clear()
            await message.answer("Нет данных о рейдах.")
            return
        latest = items[0]
        start_at = parse_coc_time(latest.get("startTime"))
        end_at = parse_coc_time(latest.get("endTime"))
        now = datetime.now(timezone.utc)
        if not start_at or not end_at or not (start_at <= now <= end_at):
            await state.clear()
            await message.answer("Сейчас нет активного рейд-уикенда.")
            return
        context["raid_id"] = latest.get("startTime") or latest.get("endTime") or "raid"
        event_type = "capital_reminder"

    if not start_at:
        await state.clear()
        await message.answer("Не удалось определить время старта события.")
        return

    fire_at = start_at + timedelta(minutes=delay_minutes)
    async with sessionmaker() as session:
        session.add(
            models.ScheduledNotification(
                category=category,
                event_type=event_type,
                fire_at=fire_at,
                message_text=reminder_text,
                created_by=message.from_user.id,
                status="pending",
                context=context,
            )
        )
        await session.commit()

    await state.clear()
    async with sessionmaker() as session:
        user = (
            await session.execute(select(models.User).where(models.User.telegram_id == message.from_user.id))
        ).scalar_one_or_none()
        prefs = _normalize_notify_pref(user.notify_pref if user else {})
    await message.answer(
        f"Личное напоминание создано: через {format_duration_ru(delay_minutes)} от старта события.",
        reply_markup=notify_menu_reply(
            bool(prefs.get("dm_enabled", False)),
            prefs.get("dm_window", "always"),
            prefs.get("dm_categories", DEFAULT_DM_CATEGORIES),
        ),
    )
