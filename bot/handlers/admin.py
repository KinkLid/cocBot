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
    admin_notify_category_reply,
    admin_notify_menu_reply,
    admin_reminder_type_reply,
    main_menu_reply,
)
from bot.services.coc_client import CocClient
from bot.services.notifications import NotificationService, normalize_chat_prefs
from bot.services.permissions import is_admin
from bot.utils.coc_time import parse_coc_time
from bot.utils.navigation import pop_menu, reset_menu, set_menu
from bot.utils.state import reset_state_if_any

logger = logging.getLogger(__name__)
router = Router()


class AdminState(StatesGroup):
    waiting_wipe_target = State()
    reminder_time_type = State()
    reminder_delay_value = State()
    reminder_clock_value = State()
    reminder_text = State()
    reminder_confirm = State()


async def _get_chat_prefs(
    sessionmaker: async_sessionmaker,
    config: BotConfig,
) -> dict:
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
                chat_id=config.main_chat_id, preferences={}
            )
            session.add(settings)
            await session.flush()
        prefs = normalize_chat_prefs(settings.preferences)
        settings.preferences = prefs
        await session.commit()
        return prefs


async def _update_chat_pref(
    sessionmaker: async_sessionmaker,
    config: BotConfig,
    category: str,
    key: str,
) -> dict:
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
                chat_id=config.main_chat_id, preferences={}
            )
            session.add(settings)
            await session.flush()
        prefs = normalize_chat_prefs(settings.preferences)
        prefs[category][key] = not prefs[category].get(key, False)
        settings.preferences = prefs
        await session.commit()
        return prefs


async def _handle_admin_escape(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> bool:
    if message.text == "Главное меню":
        await reset_state_if_any(state)
        await reset_menu(state)
        await message.answer(
            "Главное меню.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return True
    if message.text == "Назад":
        await reset_state_if_any(state)
        await _show_admin_menu_for_stack(message, state, config, sessionmaker)
        return True
    return False


async def _show_admin_menu_for_stack(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    data = await state.get_data()
    stack = list(data.get("menu_stack", []))
    current = stack[-1] if stack else None
    if current == "admin_menu":
        await message.answer("Админ-панель.", reply_markup=admin_menu_reply())
        return
    if current == "admin_notify_menu":
        await message.answer("Уведомления: общий чат.", reply_markup=admin_notify_menu_reply())
        return
    if current in {"admin_notify_war", "admin_notify_cwl", "admin_notify_capital"}:
        prefs = await _get_chat_prefs(sessionmaker, config)
        category_map = {
            "admin_notify_war": "war",
            "admin_notify_cwl": "cwl",
            "admin_notify_capital": "capital",
        }
        category = category_map[current]
        await message.answer(
            "Настройки уведомлений.",
            reply_markup=admin_notify_category_reply(category, prefs.get(category, {})),
        )
        return
    await reset_menu(state)
    await message.answer(
        "Главное меню.",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )

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
            "Укажите тип уведомления: war_preparation, war_start, war_end, cwl_round_start, cwl_round_end, "
            "capital_start, capital_end.",
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
    await reset_menu(state)
    await set_menu(state, "admin_menu")
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
async def admin_back(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await reset_state_if_any(state)
    logger.info("Admin back pressed by user_id=%s", message.from_user.id)
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Главное меню.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    previous = await pop_menu(state)
    if previous == "admin_menu":
        await message.answer("Админ-панель.", reply_markup=admin_menu_reply())
        return
    if previous == "admin_notify_menu":
        await message.answer("Уведомления: общий чат.", reply_markup=admin_notify_menu_reply())
        return
    if previous in {"admin_notify_war", "admin_notify_cwl", "admin_notify_capital"}:
        category_map = {
            "admin_notify_war": "war",
            "admin_notify_cwl": "cwl",
            "admin_notify_capital": "capital",
        }
        prefs = await _get_chat_prefs(sessionmaker, config)
        category = category_map[previous]
        await message.answer(
            "Настройки уведомлений.",
            reply_markup=admin_notify_category_reply(category, prefs.get(category, {})),
        )
        return
    await reset_menu(state)
    await message.answer(
        "Главное меню.",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )


@router.message(F.text == "Уведомления")
async def admin_notify_menu(
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
    await set_menu(state, "admin_notify_menu")
    await message.answer("Уведомления: общий чат.", reply_markup=admin_notify_menu_reply())


@router.message(F.text.in_({"Клановые войны (чат)", "ЛВК (чат)", "Рейды столицы (чат)"}))
async def admin_notify_category(
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
    category_map = {
        "Клановые войны (чат)": ("war", "admin_notify_war"),
        "ЛВК (чат)": ("cwl", "admin_notify_cwl"),
        "Рейды столицы (чат)": ("capital", "admin_notify_capital"),
    }
    category, menu_key = category_map.get(message.text, (None, None))
    if not category:
        return
    prefs = await _get_chat_prefs(sessionmaker, config)
    await set_menu(state, menu_key)
    await message.answer(
        "Настройки уведомлений.",
        reply_markup=admin_notify_category_reply(category, prefs.get(category, {})),
    )


@router.message(
    F.text.startswith("КВ:")
    | F.text.startswith("ЛВК:")
    | F.text.startswith("Столица:")
    | F.text.startswith("Итоги месяца")
)
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
    text = message.text or ""
    mapping = {
        "КВ: подготовка": ("war", "preparation"),
        "КВ: старт войны": ("war", "start"),
        "КВ: итоги": ("war", "end"),
        "КВ: напоминания": ("war", "reminder"),
        "ЛВК: старт раунда": ("cwl", "round_start"),
        "ЛВК: конец раунда": ("cwl", "round_end"),
        "ЛВК: напоминания": ("cwl", "reminder"),
        "Итоги месяца": ("cwl", "monthly_summary"),
        "Столица: старт рейдов": ("capital", "start"),
        "Столица: конец рейдов": ("capital", "end"),
        "Столица: напоминания": ("capital", "reminder"),
    }
    key = None
    category = None
    for prefix, (cat, name) in mapping.items():
        if text.startswith(prefix):
            category = cat
            key = name
            break
    if not category or not key:
        await message.answer("Не удалось определить тип.")
        return
    prefs = await _update_chat_pref(sessionmaker, config, category, key)
    await message.answer(
        "Настройки обновлены.",
        reply_markup=admin_notify_category_reply(category, prefs.get(category, {})),
    )


@router.message(
    F.text.in_({"Создать напоминание КВ", "Создать напоминание ЛВК", "Создать напоминание столицы"})
)
async def admin_create_reminder(
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
    category_map = {
        "Создать напоминание КВ": "war",
        "Создать напоминание ЛВК": "cwl",
        "Создать напоминание столицы": "capital",
    }
    category = category_map.get(message.text)
    if not category:
        await message.answer("Не удалось определить тип напоминания.", reply_markup=admin_menu_reply())
        return
    await state.update_data(reminder_category=category)
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
    sessionmaker: async_sessionmaker,
) -> None:
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    if await _handle_admin_escape(message, state, config, sessionmaker):
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
    sessionmaker: async_sessionmaker,
) -> None:
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    if await _handle_admin_escape(message, state, config, sessionmaker):
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
    sessionmaker: async_sessionmaker,
) -> None:
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    if await _handle_admin_escape(message, state, config, sessionmaker):
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
    sessionmaker: async_sessionmaker,
) -> None:
    if not is_admin(message.from_user.id, config):
        await message.answer(
            "Админ-панель доступна только администраторам.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    if await _handle_admin_escape(message, state, config, sessionmaker):
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
    if await _handle_admin_escape(message, state, config, sessionmaker):
        return
    if (message.text or "").strip().lower() not in {"да", "yes", "ок", "ok"}:
        await state.clear()
        await message.answer("Отмена.", reply_markup=admin_menu_reply())
        return
    data = await state.get_data()
    category = data.get("reminder_category")
    if category not in {"war", "cwl", "capital"}:
        await state.clear()
        await message.answer("Не удалось определить раздел напоминания.", reply_markup=admin_menu_reply())
        return

    context: dict = {}
    start_at: datetime | None = None
    if category == "war":
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
        context = {"war_tag": war_tag}
        start_at = parse_coc_time(war_data.get("startTime"))
        event_type = "war_reminder"
    elif category == "cwl":
        try:
            league = await coc_client.get_league_group(config.clan_tag)
        except Exception as exc:  # noqa: BLE001
            await state.clear()
            await message.answer(
                f"Не удалось получить данные ЛВК: {exc}",
                reply_markup=admin_menu_reply(),
            )
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
            await message.answer("Нет активного раунда ЛВК.", reply_markup=admin_menu_reply())
            return
        context = {"cwl_war_tag": war_tag, "season": league.get("season")}
        start_at = parse_coc_time(war_data.get("startTime"))
        event_type = "cwl_reminder"
    else:
        try:
            raids = await coc_client.get_capital_raid_seasons(config.clan_tag)
        except Exception as exc:  # noqa: BLE001
            await state.clear()
            await message.answer(
                f"Не удалось получить рейды столицы: {exc}",
                reply_markup=admin_menu_reply(),
            )
            return
        items = raids.get("items", [])
        if not items:
            await state.clear()
            await message.answer("Нет данных о рейдах.", reply_markup=admin_menu_reply())
            return
        latest = items[0]
        raid_id = latest.get("startTime") or latest.get("endTime") or "raid"
        start_at = parse_coc_time(latest.get("startTime"))
        end_at = parse_coc_time(latest.get("endTime"))
        now = datetime.now(timezone.utc)
        if not start_at or not end_at or not (start_at <= now <= end_at):
            await state.clear()
            await message.answer("Сейчас нет активного рейд-уикенда.", reply_markup=admin_menu_reply())
            return
        context = {"raid_id": raid_id}
        event_type = "capital_reminder"

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

    async with sessionmaker() as session:
        session.add(
            models.ScheduledNotification(
                category=category,
                event_type=event_type,
                fire_at=fire_at,
                message_text=data.get("reminder_text"),
                created_by=message.from_user.id,
                status="pending",
                context=context,
            )
        )
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
    if await _handle_admin_escape(message, state, config, sessionmaker):
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
