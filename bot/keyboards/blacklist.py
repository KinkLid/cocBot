from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def blacklist_members_kb(
    members: list[dict],
    page: int,
    page_size: int,
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    page = max(page, 1)
    start = (page - 1) * page_size
    end = start + page_size
    for member in members[start:end]:
        name = member.get("name", "Игрок")
        tag = member.get("tag", "")
        buttons.append(
            [InlineKeyboardButton(text=f"{name} ({tag})", callback_data=f"blacklist:target:{tag}")]
        )
    nav_row: list[InlineKeyboardButton] = []
    if start > 0:
        nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"blacklist:page:{page - 1}"))
    if end < len(members):
        nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"blacklist:page:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text="Отмена", callback_data="blacklist:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
