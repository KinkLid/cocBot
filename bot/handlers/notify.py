from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import (
    main_menu_reply,
)
from bot.keyboards.notify_inline import (
    notify_delay_kb,
    notify_rule_edit_kb,
    notify_rule_list_kb,
    notify_rules_action_kb,
    notify_rules_type_kb,
    notify_save_kb,
    notify_template_kb,
    user_notify_main_kb,
)
from bot.services.permissions import is_admin
from bot.services.coc_client import CocClient
from bot.services.hints import send_hint_once
from bot.texts.hints import NOTIFY_HINT
from bot.ui.labels import is_main_menu, label, label_variants
from bot.utils.navigation import pop_menu, reset_menu, set_menu
from bot.utils.notify_time import format_duration_ru_seconds
from bot.utils.state import reset_state_if_any
from bot.ui.renderers import render_cards, short_name
from bot.utils.notification_rules import schedule_rule_for_active_event
from bot.utils.notification_templates import pack_rule_text, template_label, unpack_rule_text

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
    rule_action = State()
    rule_add = State()
    rule_add_text = State()
    rule_edit_text = State()


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
            f"Сначала зарегистрируйтесь: {label('register')}",
            reply_markup=main_menu_reply(
                is_admin(message.from_user.id, config),
                is_registered=False,
            ),
        )
    return user


def _rules_table(rows: list[models.NotificationRule]) -> str:
    cards: list[str] = []
    for rule in rows:
        status = "🟢" if rule.is_enabled else "🔴"
        delay_text = format_duration_ru_seconds(rule.delay_seconds)
        template, description = unpack_rule_text(rule.custom_text)
        template_text = template_label(template) or "—"
        custom = short_name(description) or "—"
        line_one = f"{status} <b>#{html.escape(str(rule.id))}</b>"
        line_two = (
            f"└ ⏱ через {html.escape(delay_text)} • 🏷 {html.escape(template_text)}"
            f" • ✍️ {html.escape(custom)}"
        )
        cards.append(f"{line_one}\n{line_two}")
    return render_cards(cards) or "нет данных"


async def _handle_user_menu_escape(
    message: Message,
    state: FSMContext,
    config: BotConfig,
) -> bool:
    if is_main_menu(message.text):
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
    async with sessionmaker() as session:
        user = (
            await session.execute(select(models.User).where(models.User.telegram_id == message.from_user.id))
        ).scalar_one_or_none()
        if not user:
            await message.answer(
                f"Сначала зарегистрируйтесь: {label('register')}",
                reply_markup=main_menu_reply(
                    is_admin(message.from_user.id, config),
                    is_registered=False,
                ),
            )
            return
        prefs = _normalize_notify_pref(user.notify_pref)
        dm_enabled = bool(prefs.get("dm_enabled", False))
    await message.answer(
        "Раздел уведомлений.",
        reply_markup=user_notify_main_kb(dm_enabled, prefs["dm_categories"]),
    )
    await send_hint_once(
        message,
        sessionmaker,
        message.from_user.id,
        "seen_hint_notify",
        NOTIFY_HINT,
    )


async def send_notify_menu(
    bot,
    chat_id: int,
    user_id: int,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    async with sessionmaker() as session:
        user = (
            await session.execute(select(models.User).where(models.User.telegram_id == user_id))
        ).scalar_one_or_none()
        if not user:
            await bot.send_message(
                chat_id=chat_id,
                text=f"Сначала зарегистрируйтесь: {label('register')}",
                reply_markup=main_menu_reply(
                    is_admin(user_id, config),
                    is_registered=False,
                ),
            )
            return
        prefs = _normalize_notify_pref(user.notify_pref)
        dm_enabled = bool(prefs.get("dm_enabled", False))
    await bot.send_message(
        chat_id=chat_id,
        text="Раздел уведомлений.",
        reply_markup=user_notify_main_kb(dm_enabled, prefs["dm_categories"]),
    )


@router.message(F.text.in_(label_variants("notify")))
async def notify_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await notify_command(message, state, config, sessionmaker)


@router.message(F.text.in_(label_variants("notify_back")))
async def notify_back(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    await pop_menu(state)
    await notify_command(message, state, config, sessionmaker)


@router.callback_query(F.data.startswith("un:"))
async def notify_callbacks(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    data = (callback.data or "").split(":")
    if len(data) < 2:
        await callback.answer()
        return
    action = data[1]
    if action in {"menu", "back", "type", "rules", "list", "add", "pick", "pickdel", "action"}:
        await reset_state_if_any(state)
    if action == "back":
        await reset_menu(state)
        await callback.message.answer(
            "Главное меню.",
            reply_markup=main_menu_reply(is_admin(callback.from_user.id, config)),
        )
        await callback.message.edit_text("Настройки закрыты.")
        await callback.answer()
        return
    if action == "menu":
        await callback.answer()
        await notify_command(callback.message, state, config, sessionmaker)
        return
    if action == "toggle":
        if len(data) < 3:
            await callback.answer()
            return
        toggle_key = data[2]
        async with sessionmaker() as session:
            user = (
                await session.execute(
                    select(models.User).where(models.User.telegram_id == callback.from_user.id)
                )
            ).scalar_one_or_none()
            if not user:
                await callback.message.answer(
                    f"Сначала зарегистрируйтесь: {label('register')}",
                    reply_markup=main_menu_reply(
                        is_admin(callback.from_user.id, config),
                        is_registered=False,
                    ),
                )
                await callback.answer()
                return
            prefs = _normalize_notify_pref(user.notify_pref)
            if toggle_key == "dm":
                prefs["dm_enabled"] = not bool(prefs.get("dm_enabled", False))
                user.notify_pref = prefs
                await session.commit()
                if prefs["dm_enabled"]:
                    try:
                        await callback.bot.send_message(
                            chat_id=callback.from_user.id,
                            text="Проверка: уведомления будут приходить в ЛС.",
                        )
                    except TelegramForbiddenError:
                        prefs["dm_enabled"] = False
                        user.notify_pref = prefs
                        await session.commit()
                        await callback.answer("Не могу писать в ЛС.", show_alert=True)
                await callback.answer("✅ Сохранено")
            else:
                if not prefs.get("dm_enabled", False):
                    await callback.answer("Сначала включите ЛС уведомления.", show_alert=True)
                    return
                current = bool(prefs["dm_categories"].get(toggle_key, False))
                prefs["dm_categories"][toggle_key] = not current
                user.notify_pref = prefs
                await session.commit()
                await callback.answer("✅ Сохранено")
        await callback.message.edit_text(
            "Раздел уведомлений.",
            reply_markup=user_notify_main_kb(
                bool(prefs.get("dm_enabled", False)),
                prefs["dm_categories"],
            ),
        )
        return
    if action == "rules":
        await state.set_state(NotifyState.rule_action)
        await callback.message.edit_text(
            "Мои уведомления: выберите тип.",
            reply_markup=notify_rules_type_kb("un"),
        )
        await callback.answer()
        return
    if action == "action":
        if len(data) < 3:
            await callback.answer()
            return
        event_type = data[2]
        await state.update_data(rule_event_type=event_type)
        await state.set_state(NotifyState.rule_action)
        await callback.message.edit_text(
            f"Управление уведомлениями: {EVENT_LABELS.get(event_type, event_type)}.",
            reply_markup=notify_rules_action_kb("un", event_type, "rules"),
        )
        await callback.answer()
        return
    if action == "type":
        if len(data) < 3:
            await callback.answer()
            return
        event_type = data[2]
        if event_type not in EVENT_LABELS:
            await callback.answer()
            return
        await state.update_data(rule_event_type=event_type)
        await state.set_state(NotifyState.rule_action)
        await callback.message.edit_text(
            f"Управление уведомлениями: {EVENT_LABELS[event_type]}.",
            reply_markup=notify_rules_action_kb("un", event_type, "rules"),
        )
        await callback.answer()
        return
    if action == "add":
        if len(data) < 3:
            await callback.answer()
            return
        event_type = data[2]
        await state.update_data(
            rule_event_type=event_type,
            rule_delay_seconds=0,
            rule_template=None,
            rule_text=None,
            rule_delay_mode="add",
        )
        await state.set_state(NotifyState.rule_add)
        await callback.message.edit_text(
            "Выберите тип события.",
            reply_markup=notify_template_kb("un", event_type),
        )
        await callback.answer()
        return
    if action == "tmpl":
        if len(data) < 3:
            await callback.answer()
            return
        template_key = data[2]
        state_data = await state.get_data()
        event_type = state_data.get("rule_event_type")
        if event_type not in EVENT_LABELS:
            await callback.answer()
            return
        await state.update_data(rule_template=template_key, rule_delay_seconds=0)
        await callback.message.edit_text(
            "Настройте задержку уведомления.",
            reply_markup=notify_delay_kb("un", event_type, 0),
        )
        await callback.answer("⏱ Задержка: 0m")
        return
    if action == "delay":
        if len(data) < 3:
            await callback.answer()
            return
        step = data[2]
        state_data = await state.get_data()
        event_type = state_data.get("rule_event_type")
        delay_seconds = int(state_data.get("rule_delay_seconds", 0))
        if step == "reset":
            delay_seconds = 0
        elif step == "done":
            if state_data.get("rule_delay_mode") == "edit":
                rule_id = state_data.get("rule_edit_id")
                async with sessionmaker() as session:
                    rule = (
                        await session.execute(
                            select(models.NotificationRule)
                            .where(models.NotificationRule.id == rule_id)
                            .where(models.NotificationRule.user_id == callback.from_user.id)
                            .where(models.NotificationRule.event_type == event_type)
                        )
                    ).scalar_one_or_none()
                    if not rule:
                        await callback.answer("Уведомление не найдено.", show_alert=True)
                        return
                    rule.delay_seconds = delay_seconds
                    await session.commit()
                await state.clear()
                await callback.message.edit_text(
                    "✅ Задержка обновлена.",
                    reply_markup=notify_rule_edit_kb("un", event_type, rule_id, rule.is_enabled),
                )
                await callback.answer("✅ Сохранено")
                return
            await callback.message.edit_text(
                f"⏱ Задержка: {format_duration_ru_seconds(delay_seconds)}",
                reply_markup=notify_save_kb("un", event_type, bool(state_data.get("rule_text"))),
            )
            await callback.answer("✅ Готово")
            return
        else:
            try:
                delta = int(step)
            except ValueError:
                await callback.answer()
                return
            delay_seconds = max(0, delay_seconds + delta)
        await state.update_data(rule_delay_seconds=delay_seconds)
        await callback.message.edit_text(
            f"⏱ Задержка: {format_duration_ru_seconds(delay_seconds)}",
            reply_markup=notify_delay_kb("un", event_type, delay_seconds),
        )
        await callback.answer()
        return
    if action == "text":
        await state.set_state(NotifyState.rule_add_text)
        await callback.message.answer("Введите текст уведомления одним сообщением.")
        await callback.answer()
        return
    if action == "save":
        state_data = await state.get_data()
        event_type = state_data.get("rule_event_type")
        delay_seconds = int(state_data.get("rule_delay_seconds", 0))
        template_key = state_data.get("rule_template")
        description = state_data.get("rule_text")
        if event_type not in EVENT_LABELS:
            await callback.answer()
            return
        custom_text = pack_rule_text(template_key, description)
        async with sessionmaker() as session:
            rule = models.NotificationRule(
                scope="dm",
                user_id=callback.from_user.id,
                event_type=event_type,
                delay_seconds=delay_seconds,
                custom_text=custom_text,
                is_enabled=True,
            )
            session.add(rule)
            await session.flush()
            await schedule_rule_for_active_event(session, coc_client, config, rule)
            await session.commit()
        await state.clear()
        await callback.message.edit_text(
            f"Создано: {template_label(template_key) or 'Событие'} • "
            f"⏱ {format_duration_ru_seconds(delay_seconds)} • статус: включено",
            reply_markup=notify_rules_action_kb("un", event_type, "rules"),
        )
        await callback.answer("✅ Сохранено")
        return
    if action == "list":
        if len(data) < 4:
            await callback.answer()
            return
        event_type = data[2]
        page = max(int(data[3]), 1)
        async with sessionmaker() as session:
            rules = (
                await session.execute(
                    select(models.NotificationRule)
                    .where(models.NotificationRule.user_id == callback.from_user.id)
                    .where(models.NotificationRule.event_type == event_type)
                    .order_by(models.NotificationRule.created_at.desc())
                )
            ).scalars().all()
        if not rules:
            await callback.message.edit_text(
                "Активных уведомлений нет.",
                reply_markup=notify_rules_action_kb("un", event_type, "rules"),
            )
            await callback.answer()
            return
        page_size = 5
        start = (page - 1) * page_size
        end = start + page_size
        total_pages = max(1, (len(rules) + page_size - 1) // page_size)
        visible = rules[start:end]
        await callback.message.edit_text(
            f"Уведомления: {EVENT_LABELS[event_type]}.\n{_rules_table(visible)}",
            reply_markup=notify_rule_list_kb("un", event_type, visible, page, total_pages),
            parse_mode=ParseMode.HTML,
        )
        await callback.answer()
        return
    if action in {"pick", "pickdel"}:
        if len(data) < 3:
            await callback.answer()
            return
        event_type = data[2]
        async with sessionmaker() as session:
            rules = (
                await session.execute(
                    select(models.NotificationRule)
                    .where(models.NotificationRule.user_id == callback.from_user.id)
                    .where(models.NotificationRule.event_type == event_type)
                    .order_by(models.NotificationRule.created_at.desc())
                )
            ).scalars().all()
        if not rules:
            await callback.message.edit_text(
                "Активных уведомлений нет.",
                reply_markup=notify_rules_action_kb("un", event_type, "rules"),
            )
            await callback.answer()
            return
        page_size = 5
        visible = rules[:page_size]
        total_pages = max(1, (len(rules) + page_size - 1) // page_size)
        await callback.message.edit_text(
            f"Выберите уведомление для действия.\n{_rules_table(visible)}",
            reply_markup=notify_rule_list_kb("un", event_type, visible, 1, total_pages),
            parse_mode=ParseMode.HTML,
        )
        await callback.answer()
        return
    if action in {"edit", "toggle", "delete", "editdelay", "edittext"}:
        if len(data) < 4:
            await callback.answer()
            return
        event_type = data[2]
        rule_id = int(data[3])
        async with sessionmaker() as session:
            rule = (
                await session.execute(
                    select(models.NotificationRule)
                    .where(models.NotificationRule.id == rule_id)
                    .where(models.NotificationRule.user_id == callback.from_user.id)
                    .where(models.NotificationRule.event_type == event_type)
                )
            ).scalar_one_or_none()
            if not rule:
                await callback.answer("Уведомление не найдено.", show_alert=True)
                return
            if action == "toggle":
                rule.is_enabled = not rule.is_enabled
                await session.commit()
                status_text = "🔔 Включено" if rule.is_enabled else "🔕 Выключено"
                await callback.answer(status_text)
                await callback.message.edit_text(
                    status_text,
                    reply_markup=notify_rule_edit_kb("un", event_type, rule.id, rule.is_enabled),
                )
                return
            if action == "delete":
                await session.delete(rule)
                await session.commit()
                await callback.answer("🗑 Удалено")
                await callback.message.edit_text(
                    "Уведомление удалено.",
                    reply_markup=notify_rules_action_kb("un", event_type, "rules"),
                )
                return
            if action == "edit":
                await state.update_data(rule_edit_id=rule.id, rule_event_type=event_type)
                await callback.message.edit_text(
                    f"Уведомление #{rule.id}.",
                    reply_markup=notify_rule_edit_kb("un", event_type, rule.id, rule.is_enabled),
                )
                await callback.answer()
                return
            if action == "editdelay":
                await state.update_data(rule_edit_id=rule.id, rule_event_type=event_type)
                await state.set_state(NotifyState.rule_add)
                await state.update_data(rule_delay_seconds=rule.delay_seconds, rule_delay_mode="edit")
                await callback.message.edit_text(
                    f"⏱ Задержка: {format_duration_ru_seconds(rule.delay_seconds)}",
                    reply_markup=notify_delay_kb("un", event_type, rule.delay_seconds),
                )
                await callback.answer()
                return
            if action == "edittext":
                await state.update_data(rule_edit_id=rule.id, rule_event_type=event_type)
                await state.set_state(NotifyState.rule_edit_text)
                await callback.message.answer("Введите новый текст уведомления одним сообщением.")
                await callback.answer()
                return
    await callback.answer()


@router.message(NotifyState.rule_add_text)
async def notify_rule_add_text(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    if await _handle_user_menu_escape(message, state, config):
        return
    text = (message.text or "").strip()
    await state.update_data(rule_text=text)
    state_data = await state.get_data()
    delay_seconds = int(state_data.get("rule_delay_seconds", 0))
    event_type = state_data.get("rule_event_type")
    await message.answer(
        f"⏱ Задержка: {format_duration_ru_seconds(delay_seconds)}",
        reply_markup=notify_save_kb("un", event_type, True),
    )


@router.message(NotifyState.rule_edit_text)
async def notify_rule_edit_text_input(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    if await _handle_user_menu_escape(message, state, config):
        return
    data = await state.get_data()
    rule_id = data.get("rule_edit_id")
    event_type = data.get("rule_event_type")
    if not rule_id or event_type not in EVENT_LABELS:
        await state.clear()
        await notify_command(message, state, config, sessionmaker)
        return
    text = (message.text or "").strip()
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
            await message.answer("Уведомление не найдено.")
            await state.clear()
            return
        template_key, _ = unpack_rule_text(rule.custom_text)
        rule.custom_text = pack_rule_text(template_key, text)
        await session.commit()
    await state.clear()
    await message.answer(
        "✅ Сохранено.",
        reply_markup=notify_rule_edit_kb("un", event_type, rule_id, rule.is_enabled),
    )
