from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from aiogram.types import Message
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import (
    main_menu_reply,
    notify_menu_reply,
    notify_rules_action_reply,
    notify_rules_type_reply,
)
from bot.services.permissions import is_admin
from bot.services.coc_client import CocClient
from bot.utils.navigation import pop_menu, reset_menu, set_menu
from bot.utils.notify_time import format_duration_ru, parse_delay_to_minutes
from bot.utils.state import reset_state_if_any
from bot.utils.tables import build_pre_table
from bot.utils.notification_rules import schedule_rule_for_active_event

router = Router()

DEFAULT_DM_CATEGORIES = {
    "war": False,
    "cwl": False,
    "capital": False,
}

EVENT_LABELS = {
    "war": "КВ",
    "cwl": "ЛВК",
    "capital": "Рейды",
}


class NotifyState(StatesGroup):
    rule_choose_type = State()
    rule_action = State()
    rule_delay_value = State()
    rule_text = State()
    rule_edit_id = State()
    rule_edit_delay = State()
    rule_edit_text = State()
    rule_toggle_delete = State()


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


async def _get_user_or_prompt(
    message: Message,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> models.User | None:
    async with sessionmaker() as session:
        user = (
            await session.execute(select(models.User).where(models.User.telegram_id == message.from_user.id))
        ).scalar_one_or_none()
    if not user:
        await message.answer(
            "Вы ещё не зарегистрированы. Нажмите «Регистрация».",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
    return user


def _rules_table(rows: list[models.NotificationRule]) -> str:
    table_rows: list[list[str]] = []
    for rule in rows:
        status = "ВКЛ" if rule.is_enabled else "ВЫКЛ"
        delay_text = format_duration_ru(rule.delay_seconds // 60)
        custom = rule.custom_text or "—"
        table_rows.append([str(rule.id), delay_text, status, custom])
    return build_pre_table(
        ["ID", "Задержка", "Статус", "Текст"],
        table_rows,
        max_widths=[5, 10, 6, 24],
    )


async def _handle_user_menu_escape(
    message: Message,
    state: FSMContext,
    config: BotConfig,
) -> bool:
    if message.text == "Главное меню":
        await reset_state_if_any(state)
        await reset_menu(state)
        await message.answer(
            "Главное меню.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return True
    return False


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
        "Раздел уведомлений.",
        reply_markup=notify_menu_reply(dm_enabled, prefs["dm_window"], prefs["dm_categories"]),
    )


@router.message(F.text == "🔔 Уведомления")
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


@router.message(F.text == "🔔 Личные уведомления")
async def notify_rules_menu(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    user = await _get_user_or_prompt(message, config, sessionmaker)
    if not user:
        return
    prefs = _normalize_notify_pref(user.notify_pref)
    if not prefs.get("dm_enabled", False):
        await message.answer(
            "Сначала включите личные уведомления.",
            reply_markup=notify_menu_reply(False, prefs["dm_window"], prefs["dm_categories"]),
        )
        return
    await state.set_state(NotifyState.rule_choose_type)
    await message.answer(
        "Выберите тип уведомлений.",
        reply_markup=notify_rules_type_reply(),
    )


@router.message(NotifyState.rule_choose_type)
async def notify_rules_choose_type(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    if await _handle_user_menu_escape(message, state, config):
        return
    if message.text == "Назад":
        await notify_command(message, state, config, sessionmaker)
        return
    event_type = {"КВ": "war", "ЛВК": "cwl", "Рейды": "capital"}.get(message.text)
    if not event_type:
        await message.answer("Нужно выбрать вариант.", reply_markup=notify_rules_type_reply())
        return
    await state.update_data(rule_event_type=event_type)
    await state.set_state(NotifyState.rule_action)
    await message.answer(
        f"Управление уведомлениями: {EVENT_LABELS[event_type]}.",
        reply_markup=notify_rules_action_reply(),
    )


@router.message(NotifyState.rule_action)
async def notify_rules_action(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    if await _handle_user_menu_escape(message, state, config):
        return
    if message.text == "Назад":
        await state.set_state(NotifyState.rule_choose_type)
        await message.answer("Выберите тип уведомлений.", reply_markup=notify_rules_type_reply())
        return
    data = await state.get_data()
    event_type = data.get("rule_event_type")
    if event_type not in EVENT_LABELS:
        await state.clear()
        await notify_command(message, state, config, sessionmaker)
        return
    if message.text == "➕ Добавить уведомление":
        await state.set_state(NotifyState.rule_delay_value)
        await message.answer(
            "Введите задержку от старта события (например, 1h, 30m, 0.1h).",
            reply_markup=notify_rules_action_reply(),
        )
        return
    if message.text == "📋 Активные уведомления":
        async with sessionmaker() as session:
            rules = (
                await session.execute(
                    select(models.NotificationRule)
                    .where(models.NotificationRule.user_id == message.from_user.id)
                    .where(models.NotificationRule.event_type == event_type)
                    .order_by(models.NotificationRule.created_at.desc())
                )
            ).scalars().all()
        if not rules:
            await message.answer("Активных уведомлений нет.", reply_markup=notify_rules_action_reply())
            return
        await message.answer(
            f"Уведомления: {EVENT_LABELS[event_type]}.\n{_rules_table(rules)}",
            reply_markup=notify_rules_action_reply(),
            parse_mode=ParseMode.HTML,
        )
        return
    if message.text == "✏️ Изменить уведомление":
        await state.set_state(NotifyState.rule_edit_id)
        await message.answer("Введите ID уведомления для изменения.", reply_markup=notify_rules_action_reply())
        return
    if message.text == "🗑 Удалить / Отключить уведомление":
        await state.set_state(NotifyState.rule_toggle_delete)
        await message.answer(
            "Введите ID и действие: включить, отключить или удалить. Пример: 12 отключить.",
            reply_markup=notify_rules_action_reply(),
        )
        return
    await message.answer("Нужно выбрать действие.", reply_markup=notify_rules_action_reply())


@router.message(NotifyState.rule_delay_value)
async def notify_rule_delay_value(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    if await _handle_user_menu_escape(message, state, config):
        return
    if message.text == "Назад":
        await state.set_state(NotifyState.rule_action)
        await message.answer("Выберите действие.", reply_markup=notify_rules_action_reply())
        return
    delay_minutes = parse_delay_to_minutes(message.text or "")
    if not delay_minutes:
        await message.answer("Нужен формат 1h, 30m или 0.1h.", reply_markup=notify_rules_action_reply())
        return
    await state.update_data(rule_delay_minutes=delay_minutes)
    await state.set_state(NotifyState.rule_text)
    await message.answer("Введите текст уведомления или '-' без текста.", reply_markup=notify_rules_action_reply())


@router.message(NotifyState.rule_text)
async def notify_rule_text(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if await _handle_user_menu_escape(message, state, config):
        return
    if message.text == "Назад":
        await state.set_state(NotifyState.rule_action)
        await message.answer("Выберите действие.", reply_markup=notify_rules_action_reply())
        return
    data = await state.get_data()
    event_type = data.get("rule_event_type")
    delay_minutes = data.get("rule_delay_minutes")
    if event_type not in EVENT_LABELS or not delay_minutes:
        await state.clear()
        await notify_command(message, state, config, sessionmaker)
        return
    text = (message.text or "").strip()
    custom_text = "" if text == "-" else text
    async with sessionmaker() as session:
        rule = models.NotificationRule(
            scope="dm",
            user_id=message.from_user.id,
            event_type=event_type,
            delay_seconds=int(delay_minutes * 60),
            custom_text=custom_text,
            is_enabled=True,
        )
        session.add(rule)
        await session.flush()
        await schedule_rule_for_active_event(session, coc_client, config, rule)
        await session.commit()
    await state.set_state(NotifyState.rule_action)
    await message.answer(
        f"Уведомление добавлено: через {format_duration_ru(delay_minutes)}.",
        reply_markup=notify_rules_action_reply(),
    )


@router.message(NotifyState.rule_edit_id)
async def notify_rule_edit_id(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    if await _handle_user_menu_escape(message, state, config):
        return
    if message.text == "Назад":
        await state.set_state(NotifyState.rule_action)
        await message.answer("Выберите действие.", reply_markup=notify_rules_action_reply())
        return
    if not (message.text or "").isdigit():
        await message.answer("Нужен числовой ID.", reply_markup=notify_rules_action_reply())
        return
    await state.update_data(rule_edit_id=int(message.text))
    await state.set_state(NotifyState.rule_edit_delay)
    await message.answer(
        "Введите новую задержку (1h, 30m) или '-' чтобы оставить.",
        reply_markup=notify_rules_action_reply(),
    )


@router.message(NotifyState.rule_edit_delay)
async def notify_rule_edit_delay(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    if await _handle_user_menu_escape(message, state, config):
        return
    if message.text == "Назад":
        await state.set_state(NotifyState.rule_action)
        await message.answer("Выберите действие.", reply_markup=notify_rules_action_reply())
        return
    text = (message.text or "").strip()
    delay_minutes = None
    if text != "-":
        delay_minutes = parse_delay_to_minutes(text)
        if not delay_minutes:
            await message.answer("Нужен формат 1h, 30m или '-'.", reply_markup=notify_rules_action_reply())
            return
    await state.update_data(rule_edit_delay=delay_minutes)
    await state.set_state(NotifyState.rule_edit_text)
    await message.answer(
        "Введите новый текст или '-' чтобы оставить.",
        reply_markup=notify_rules_action_reply(),
    )


@router.message(NotifyState.rule_edit_text)
async def notify_rule_edit_text(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    if await _handle_user_menu_escape(message, state, config):
        return
    if message.text == "Назад":
        await state.set_state(NotifyState.rule_action)
        await message.answer("Выберите действие.", reply_markup=notify_rules_action_reply())
        return
    data = await state.get_data()
    event_type = data.get("rule_event_type")
    rule_id = data.get("rule_edit_id")
    if event_type not in EVENT_LABELS or not rule_id:
        await state.clear()
        await notify_command(message, state, config, sessionmaker)
        return
    new_delay = data.get("rule_edit_delay")
    text_input = (message.text or "").strip()
    custom_text = None if text_input == "-" else text_input
    async with sessionmaker() as session:
        rule = (
            await session.execute(
                select(models.NotificationRule)
                .where(models.NotificationRule.id == rule_id)
                .where(models.NotificationRule.user_id == message.from_user.id)
                .where(models.NotificationRule.event_type == event_type)
            )
        ).scalar_one_or_none()
        if not rule:
            await message.answer("Уведомление не найдено.", reply_markup=notify_rules_action_reply())
            await state.set_state(NotifyState.rule_action)
            return
        if new_delay is not None:
            rule.delay_seconds = int(new_delay * 60)
        if custom_text is not None:
            rule.custom_text = custom_text
        await session.commit()
    await state.set_state(NotifyState.rule_action)
    await message.answer("Уведомление обновлено.", reply_markup=notify_rules_action_reply())


@router.message(NotifyState.rule_toggle_delete)
async def notify_rule_toggle_delete(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    if await _handle_user_menu_escape(message, state, config):
        return
    if message.text == "Назад":
        await state.set_state(NotifyState.rule_action)
        await message.answer("Выберите действие.", reply_markup=notify_rules_action_reply())
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[0].isdigit():
        await message.answer(
            "Нужен формат: ID действие (включить/отключить/удалить).",
            reply_markup=notify_rules_action_reply(),
        )
        return
    rule_id = int(parts[0])
    action = parts[1].lower()
    data = await state.get_data()
    event_type = data.get("rule_event_type")
    if event_type not in EVENT_LABELS:
        await state.clear()
        await notify_command(message, state, config, sessionmaker)
        return
    async with sessionmaker() as session:
        rule = (
            await session.execute(
                select(models.NotificationRule)
                .where(models.NotificationRule.id == rule_id)
                .where(models.NotificationRule.user_id == message.from_user.id)
                .where(models.NotificationRule.event_type == event_type)
            )
        ).scalar_one_or_none()
        if not rule:
            await message.answer("Уведомление не найдено.", reply_markup=notify_rules_action_reply())
            return
        if action.startswith("удал"):
            await session.delete(rule)
            await session.commit()
            await message.answer("Уведомление удалено.", reply_markup=notify_rules_action_reply())
            return
        if action.startswith("откл"):
            rule.is_enabled = False
        elif action.startswith("вкл"):
            rule.is_enabled = True
        else:
            await message.answer("Действие: включить, отключить или удалить.", reply_markup=notify_rules_action_reply())
            return
        await session.commit()
    await message.answer("Готово.", reply_markup=notify_rules_action_reply())
