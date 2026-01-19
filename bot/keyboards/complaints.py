from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def complaints_members_kb(
    members: list[dict],
    page: int,
    page_size: int = 10,
) -> InlineKeyboardMarkup:
    page = max(page, 1)
    start = (page - 1) * page_size
    end = start + page_size
    buttons: list[list[InlineKeyboardButton]] = []
    for member in members[start:end]:
        name = member.get("name", "Игрок")
        tag = member.get("tag", "")
        buttons.append(
            [InlineKeyboardButton(text=f"{name} ({tag})", callback_data=f"complaint:target:{tag}")]
        )

    nav_row: list[InlineKeyboardButton] = []
    if start > 0:
        nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"complaint:page:{page - 1}"))
    if end < len(members):
        nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"complaint:page:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton(text="Отмена", callback_data="complaint:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def complaint_admin_kb(complaint_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"complaint:delete:{complaint_id}")]
        ]
    )


def complaint_text_reply() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Главное меню")]],
        resize_keyboard=True,
    )
