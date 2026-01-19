from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import BotConfig
from bot.db import models
from bot.keyboards.common import admin_menu_reply, main_menu_reply
from bot.keyboards.complaints import complaint_admin_kb, complaint_text_reply, complaints_members_kb
from bot.services.coc_client import CocClient
from bot.services.complaints import build_complaint_message, notify_admins_about_complaint
from bot.services.permissions import is_admin
from bot.utils.navigation import reset_menu
from bot.utils.state import reset_state_if_any
from bot.utils.validators import normalize_tag

logger = logging.getLogger(__name__)
router = Router()

COMPLAINTS_PAGE_SIZE = 10


class ComplaintState(StatesGroup):
    choosing_target = State()
    waiting_text = State()


def _display_name(user) -> str:
    username = f"@{user.username}" if user.username else ""
    full_name = user.full_name or ""
    if username and full_name:
        return f"{username} ({full_name})"
    return username or full_name or "пользователь"


async def _load_clan_members(coc_client: CocClient, clan_tag: str) -> list[dict]:
    data = await coc_client.get_clan_members(clan_tag)
    members = data.get("items", [])
    return sorted(members, key=lambda member: member.get("clanRank") or 0)


async def start_complaint_flow(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
) -> None:
    await reset_state_if_any(state)
    await reset_menu(state)
    try:
        members = await _load_clan_members(coc_client, config.clan_tag)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load clan members for complaints: %s", exc)
        await message.answer(
            "Не удалось загрузить список игроков клана. Попробуйте позже.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    if not members:
        await message.answer(
            "Список игроков клана пуст. Попробуйте позже.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await state.set_state(ComplaintState.choosing_target)
    await message.answer(
        "Выберите игрока клана, на которого хотите пожаловаться:",
        reply_markup=complaints_members_kb(members, page=1, page_size=COMPLAINTS_PAGE_SIZE),
    )


@router.message(F.text == "📣 Жалоба")
async def complaint_button(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
) -> None:
    await start_complaint_flow(message, state, config, coc_client)


@router.message(Command("complaint"))
async def complaint_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
) -> None:
    await start_complaint_flow(message, state, config, coc_client)


@router.callback_query(F.data.startswith("complaint:page:"))
async def complaint_pagination(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
) -> None:
    await callback.answer()
    try:
        page = int((callback.data or "").split(":")[-1])
    except ValueError:
        return
    try:
        members = await _load_clan_members(coc_client, config.clan_tag)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to reload clan members: %s", exc)
        if callback.message:
            await callback.message.answer(
                "Не удалось обновить список игроков. Попробуйте позже.",
                reply_markup=main_menu_reply(is_admin(callback.from_user.id, config)),
            )
        return
    if callback.message:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=complaints_members_kb(members, page=page, page_size=COMPLAINTS_PAGE_SIZE)
            )
        except TelegramBadRequest:
            return


@router.callback_query(F.data == "complaint:cancel")
async def complaint_cancel(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    await callback.answer("Отменено")
    await reset_state_if_any(state)
    await reset_menu(state)
    if callback.message:
        await callback.message.answer(
            "Жалоба отменена.",
            reply_markup=main_menu_reply(is_admin(callback.from_user.id, config)),
        )


@router.callback_query(F.data.startswith("complaint:target:"))
async def complaint_select_target(
    callback: CallbackQuery,
    state: FSMContext,
    config: BotConfig,
    coc_client: CocClient,
) -> None:
    await callback.answer()
    tag = (callback.data or "").split(":", 2)[-1]
    normalized_tag = normalize_tag(tag)
    try:
        members = await _load_clan_members(coc_client, config.clan_tag)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to reload clan members for target: %s", exc)
        if callback.message:
            await callback.message.answer(
                "Не удалось проверить игрока. Попробуйте позже.",
                reply_markup=main_menu_reply(is_admin(callback.from_user.id, config)),
            )
        return
    target = None
    for member in members:
        member_tag = normalize_tag(member.get("tag", ""))
        if member_tag == normalized_tag:
            target = member
            break
    if not target:
        if callback.message:
            await callback.message.answer(
                "Игрок не найден в клане. Выберите другого.",
                reply_markup=main_menu_reply(is_admin(callback.from_user.id, config)),
            )
        return

    await state.set_state(ComplaintState.waiting_text)
    await state.update_data(
        target_player_tag=normalized_tag,
        target_player_name=target.get("name", "Игрок"),
    )
    if callback.message:
        await callback.message.answer(
            f"Напишите текст жалобы на {target.get('name', 'Игрок')} ({normalized_tag}):",
            reply_markup=complaint_text_reply(),
        )


@router.message(ComplaintState.choosing_target)
async def complaint_choose_target_message(
    message: Message,
    state: FSMContext,
    config: BotConfig,
) -> None:
    if message.text == "Главное меню":
        await reset_state_if_any(state)
        await reset_menu(state)
        await message.answer(
            "Главное меню.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    await message.answer(
        "Нужно выбрать игрока кнопкой ниже.",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )


@router.message(ComplaintState.waiting_text)
async def complaint_text(
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
    text = (message.text or "").strip()
    if not text:
        await message.answer(
            "Напишите текст жалобы.",
            reply_markup=complaint_text_reply(),
        )
        return
    data = await state.get_data()
    target_tag = data.get("target_player_tag")
    target_name = data.get("target_player_name")
    if not target_tag or not target_name:
        await reset_state_if_any(state)
        await message.answer(
            "Не удалось определить игрока. Нажмите «📣 Жалоба» ещё раз.",
            reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
        )
        return
    created_by_name = _display_name(message.from_user)
    complaint = models.Complaint(
        created_by_tg_id=message.from_user.id,
        created_by_tg_name=created_by_name,
        target_player_tag=target_tag,
        target_player_name=target_name,
        text=text,
        type="user",
        status="open",
    )
    async with sessionmaker() as session:
        session.add(complaint)
        await session.commit()
        await session.refresh(complaint)

    await notify_admins_about_complaint(message.bot, config, complaint)
    await reset_state_if_any(state)
    await reset_menu(state)
    await message.answer(
        "Жалоба отправлена админам ✅",
        reply_markup=main_menu_reply(is_admin(message.from_user.id, config)),
    )


@router.message(F.text == "📣 Жалобы")
async def admin_complaints_list(
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
        complaints = (
            await session.execute(
                select(models.Complaint)
                .where(models.Complaint.status != "deleted")
                .order_by(models.Complaint.created_at.desc())
                .limit(20)
            )
        ).scalars().all()
    if not complaints:
        await message.answer("Жалоб нет.", reply_markup=admin_menu_reply())
        return
    await message.answer(
        f"Последние жалобы: {len(complaints)} (показаны свежие).",
        reply_markup=admin_menu_reply(),
    )
    for complaint in complaints:
        await message.answer(
            build_complaint_message(complaint, config.timezone),
            parse_mode=ParseMode.HTML,
            reply_markup=complaint_admin_kb(complaint.id),
        )


@router.message(Command("complaints"))
async def admin_complaints_command(
    message: Message,
    state: FSMContext,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await admin_complaints_list(message, state, config, sessionmaker)


@router.callback_query(F.data.startswith("complaint:delete:"))
async def complaint_delete(
    callback: CallbackQuery,
    config: BotConfig,
    sessionmaker: async_sessionmaker,
) -> None:
    await callback.answer()
    if not is_admin(callback.from_user.id, config):
        await callback.answer("Доступ только для админов.")
        return
    try:
        complaint_id = int((callback.data or "").split(":")[-1])
    except ValueError:
        return
    async with sessionmaker() as session:
        complaint = (
            await session.execute(select(models.Complaint).where(models.Complaint.id == complaint_id))
        ).scalar_one_or_none()
        if not complaint:
            await callback.answer("Жалоба не найдена.")
            return
        if complaint.status == "deleted":
            await callback.answer("Жалоба уже удалена.")
            return
        complaint.status = "deleted"
        await session.commit()
    await callback.answer("Жалоба удалена.")
    if callback.message:
        await callback.message.edit_text("Жалоба удалена.")
