from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import (
    admin_action_reply,
    admin_menu_reply,
    admin_notify_reply,
    admin_reminder_type_reply,
    main_menu_reply,
)
from bot.services.coc_client import CocClient
from bot.services.notifications import NotificationService
from bot.services.permissions import is_admin
from bot.utils.coc_time import parse_coc_time
from bot.utils.state import reset_state_if_any

logger = logging.getLogger(__name__)
router = Router()
DEFAULT_CHAT_TYPES = {
    "preparation": True,
    "inWar": True,
    "warEnded": True,
    "cwlEnded": True,
}


class AdminState(StatesGroup):
    waiting_wipe_target = State()
    reminder_time_type = State()
    reminder_delay_value = State()
    reminder_clock_value = State()
    reminder_text = State()
    reminder_confirm = State()

@router.message(Command("notifytest"))
async def admin_notify_test(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Использование: /notifytest preparation|inWar|warEnded|cwlEnded",
            reply_markup=admin_menu_reply(),
        )
        return
    notify_type = args[1].strip()
    notifier = NotificationService(message.bot, config, sessionmaker, coc_client)
    await notifier.send_test_notification(notify_type)
    await message.answer("Тестовое уведомление отправлено.", reply_markup=admin_menu_reply())

@router.message(Command("wipe"))
async def wipe_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await state.set_state(AdminState.waiting_wipe_target)
    await message.answer(
        "Пришлите тег игрока или ответьте на сообщение пользователя.",
        reply_markup=admin_action_reply(),
    )


@router.message(F.text == "Админ-панель")
async def admin_panel_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await message.answer("Админ-панель.", reply_markup=admin_menu_reply())


@router.message(F.text == "Очистить игрока")
async def wipe_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await state.set_state(AdminState.waiting_wipe_target)
    await message.answer(
        "Пришлите тег игрока или ответьте на сообщение пользователя.",
        reply_markup=admin_action_reply(),
    )


@router.message(F.text == "Диагностика")
async def diagnostics_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    async with sessionmaker() as session:
        users_count = (await session.execute(select(models.User))).scalars().all()
        wars_count = (await session.execute(select(models.War))).scalars().all()
    await message.answer(
        f"Диагностика: пользователей {len(users_count)}, войн {len(wars_count)}.",
        reply_markup=admin_menu_reply(),
    )


@router.message(F.text == "Назад")
async def admin_back(message: Message, state: FSMContext, config: BotConfig) -> None:
    current_state = await state.get_state()
    await reset_state_if_any(state)
    logger.info("Admin back pressed by user_id=%s", message.from_user.id)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Главное меню.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    if current_state:
        await message.answer("Админ-панель.", reply_markup=admin_menu_reply())
        return
    await message.answer(
        "Главное меню.",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )


@router.message(F.text == "Настройки уведомлений чата")
async def admin_notify_settings(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    async with sessionmaker() as session:
        settings = (
            await session.execute(
                select(models.ChatNotificationSetting).where(
                    models.ChatNotificationSetting.chat_id == config.main_chat_id
                )
            )
        ).scalar_one_or_none()
        if not settings:
            settings = models.ChatNotificationSetting(
                chat_id=config.main_chat_id, preferences={"types": DEFAULT_CHAT_TYPES}
            )
            session.add(settings)
            await session.commit()
        chat_types = dict(settings.preferences or {}).get("types", {})
    await message.answer(
        "Настройки уведомлений чата.",
        reply_markup=admin_notify_reply(chat_types),
    )


@router.message(F.text.startswith("Чат W1 подготовка"))
@router.message(F.text.startswith("Чат W2 война"))
@router.message(F.text.startswith("Чат W3 итог"))
@router.message(F.text.startswith("Чат W4 ЛВК"))
async def admin_notify_toggle(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    mapping = {
        "Чат W1 подготовка": "preparation",
        "Чат W2 война": "inWar",
        "Чат W3 итог": "warEnded",
        "Чат W4 ЛВК": "cwlEnded",
    }
    label = message.text.split(":")[0].strip()
    key = mapping.get(label)
    if not key:
        await message.answer("Неизвестный тип.")
        return
    async with sessionmaker() as session:
        settings = (
            await session.execute(
                select(models.ChatNotificationSetting).where(
                    models.ChatNotificationSetting.chat_id == config.main_chat_id
                )
            )
        ).scalar_one_or_none()
        if not settings:
            settings = models.ChatNotificationSetting(
                chat_id=config.main_chat_id, preferences={"types": DEFAULT_CHAT_TYPES}
            )
            session.add(settings)
        prefs = dict(settings.preferences or {})
        types = dict(prefs.get("types", {}))
        types[key] = not types.get(key, True)
        prefs["types"] = types
        settings.preferences = prefs
        await session.commit()
    await message.answer(
        "Настройки обновлены.",
        reply_markup=admin_notify_reply(types),
    )


@router.message(F.text == "Назад в админку")
async def admin_notify_back(
    message: Message,
    state: FSMContext,
    config: BotConfig,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Главное меню.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await message.answer("Админ-панель.", reply_markup=admin_menu_reply())


@router.message(F.text == "Создать напоминание о войне")
async def admin_create_war_reminder(
    message: Message,
    state: FSMContext,
    config: BotConfig,
) -> None:
    await reset_state_if_any(state)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await state.set_state(AdminState.reminder_time_type)
    await message.answer(
        "Когда отправить напоминание?",
        reply_markup=admin_reminder_type_reply(),
    )


@router.message(AdminState.reminder_time_type)
async def admin_reminder_time_type(
    message: Message,
    state: FSMContext,
    config: BotConfig,
) -> None:
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    text = (message.text or "").strip().lower()
    if text.startswith("через"):
        await state.update_data(reminder_mode="delay")
        await state.set_state(AdminState.reminder_delay_value)
        await message.answer("Введите количество часов (например, 12).", reply_markup=admin_action_reply())
        return
    if text.startswith("время"):
        await state.update_data(reminder_mode="clock")
        await state.set_state(AdminState.reminder_clock_value)
        await message.answer("Введите время HH:MM (например, 19:30).", reply_markup=admin_action_reply())
        return
    await message.answer("Нужно выбрать вариант.", reply_markup=admin_reminder_type_reply())


@router.message(AdminState.reminder_delay_value)
async def admin_reminder_delay_value(
    message: Message,
    state: FSMContext,
    config: BotConfig,
) -> None:
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) <= 0:
        await message.answer("Введите положительное число часов.", reply_markup=admin_action_reply())
        return
    await state.update_data(reminder_value=int(text))
    await state.set_state(AdminState.reminder_text)
    await message.answer("Введите короткое описание напоминания.", reply_markup=admin_action_reply())


@router.message(AdminState.reminder_clock_value)
async def admin_reminder_clock_value(
    message: Message,
    state: FSMContext,
    config: BotConfig,
) -> None:
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    text = (message.text or "").strip()
    if len(text.split(":")) != 2:
        await message.answer("Нужно время в формате HH:MM.", reply_markup=admin_action_reply())
        return
    hours, minutes = text.split(":", 1)
    if not hours.isdigit() or not minutes.isdigit():
        await message.answer("Нужно время в формате HH:MM.", reply_markup=admin_action_reply())
        return
    hour = int(hours)
    minute = int(minutes)
    if hour not in range(0, 24) or minute not in range(0, 60):
        await message.answer("Часы 0-23, минуты 0-59.", reply_markup=admin_action_reply())
        return
    await state.update_data(reminder_value=f"{hour:02d}:{minute:02d}")
    await state.set_state(AdminState.reminder_text)
    await message.answer("Введите короткое описание напоминания.", reply_markup=admin_action_reply())


@router.message(AdminState.reminder_text)
async def admin_reminder_text(
    message: Message,
    state: FSMContext,
    config: BotConfig,
) -> None:
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Нужно короткое описание.", reply_markup=admin_action_reply())
        return
    await state.update_data(reminder_text=text)
    await state.set_state(AdminState.reminder_confirm)
    data = await state.get_data()
    await message.answer(
        f"Подтверждение:\n"
        f"Тип: {'через N часов' if data.get('reminder_mode') == 'delay' else 'время'}\n"
        f"Значение: {data.get('reminder_value')}\n"
        f"Текст: {text}\n"
        "Напишите 'да' для подтверждения.",
        reply_markup=admin_action_reply(),
    )


@router.message(AdminState.reminder_confirm)
async def admin_reminder_confirm(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
    coc_client: CocClient,
) -> None:
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    if (message.text or "").strip().lower() not in {"да", "yes", "ок", "ok"}:
        await state.clear()
        await message.answer("Отмена.", reply_markup=admin_menu_reply())
        return
    data = await state.get_data()
    try:
        war_data = await coc_client.get_current_war(config.clan_tag)
    except Exception as exc:  # noqa: BLE001
        await state.clear()
        await message.answer(
            f"Не удалось получить данные о войне: {exc}",
            reply_markup=admin_menu_reply(),
        )
        return
    if war_data.get("state") not in {"preparation", "inWar"}:
        await state.clear()
        await message.answer("Сейчас нет активной войны.", reply_markup=admin_menu_reply())
        return
    war_tag = war_data.get("tag") or war_data.get("clan", {}).get("tag")
    start_at = parse_coc_time(war_data.get("startTime"))
    async with sessionmaker() as session:
        war = None
        if war_tag:
            war = (
                await session.execute(select(models.War).where(models.War.war_tag == war_tag))
            ).scalar_one_or_none()
        if not war:
            war = models.War(
                war_tag=war_tag,
                war_type=war_data.get("warType", "unknown"),
                state=war_data.get("state", "unknown"),
                start_at=start_at,
                end_at=parse_coc_time(war_data.get("endTime")),
                opponent_name=war_data.get("opponent", {}).get("name"),
                opponent_tag=war_data.get("opponent", {}).get("tag"),
                league_name=war_data.get("league", {}).get("name"),
            )
            session.add(war)
            await session.flush()
        if data.get("reminder_mode") == "delay":
            base_time = start_at or datetime.now(timezone.utc)
            fire_at = base_time + timedelta(hours=int(data["reminder_value"]))
        else:
            zone = ZoneInfo(config.timezone)
            now = datetime.now(zone)
            clock_value = data["reminder_value"]
            hour, minute = [int(x) for x in clock_value.split(":")]
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target = target + timedelta(days=1)
            fire_at = target.astimezone(timezone.utc)
        reminder = models.WarReminder(
            war_id=war.id,
            fire_at=fire_at,
            message_text=data.get("reminder_text"),
            created_by=message.from_user.id,
            status="pending",
        )
        session.add(reminder)
        await session.commit()
    await state.clear()
    await message.answer("Напоминание сохранено.", reply_markup=admin_menu_reply())


@router.message(AdminState.waiting_wipe_target)
async def wipe_target(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return

    target_user = message.reply_to_message.from_user if message.reply_to_message else None
    target_text = (message.text or "").strip()

    async with sessionmaker() as session:
        if target_user:
            user = (
                await session.execute(
                    select(models.User).where(models.User.telegram_id == target_user.id)
                )
            ).scalar_one_or_none()
        elif target_text.startswith("@"):
            user = (
                await session.execute(
                    select(models.User).where(models.User.username == target_text.lstrip("@"))
                )
            ).scalar_one_or_none()
        else:
            user = (
                await session.execute(select(models.User).where(models.User.player_tag == target_text))
            ).scalar_one_or_none()

        if not user:
            await message.answer(
                "Пользователь не найден. Попробуйте ещё раз или нажмите «Назад».",
                reply_markup=admin_action_reply(),
            )
            return

        await session.execute(
            delete(models.TargetClaim).where(models.TargetClaim.claimed_by_telegram_id == user.telegram_id)
        )
        await session.execute(
            delete(models.WarParticipation).where(models.WarParticipation.telegram_id == user.telegram_id)
        )
        await session.execute(
            delete(models.CapitalContribution).where(models.CapitalContribution.telegram_id == user.telegram_id)
        )
        await session.execute(
            delete(models.StatsDaily).where(models.StatsDaily.telegram_id == user.telegram_id)
        )
        await session.delete(user)
        await session.commit()

    await state.clear()
    await message.answer(
        "Данные пользователя удалены.",
        reply_markup=admin_menu_reply(),
    )
