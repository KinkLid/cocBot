from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.ui.labels import claimed_target_label, label, target_label
from bot.ui.renderers import short_name


def build_targets_keyboard(
    enemies: list[dict],
    mode: str,
    taken_positions: set[int],
    my_positions: set[int],
    admin_assigned_positions: set[int] | None = None,
    admin_rows: list[tuple[str, str]] | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if admin_rows:
        for text, callback in admin_rows:
            rows.append([InlineKeyboardButton(text=text, callback_data=callback)])
    sorted_enemies = sorted(enemies, key=lambda enemy: enemy.get("mapPosition") or 0)
    for enemy in sorted_enemies:
        pos = enemy.get("mapPosition")
        name = enemy.get("name") or "?"
        th = enemy.get("townhallLevel")
        if mode == "admin":
            status = "занято" if pos in taken_positions else "свободно"
            status_icon = "✅" if pos in taken_positions else "⬜"
            if admin_assigned_positions and pos in admin_assigned_positions:
                status_icon = "🛠✅"
            th_label = f"TH{th}" if th else ""
            name_label = short_name(name)
            base = f"#{pos} {th_label}".strip()
            detail = f"{base} ({status})"
            if name_label and name_label != "?":
                detail = f"{detail} · {name_label}"
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"{status_icon} {detail}",
                        callback_data=f"targets:admin-select:{pos}",
                    )
                ]
            )
            continue
        base = f"#{pos} {name} TH{th}" if th else f"#{pos} {name}"
        if pos in my_positions:
            text = claimed_target_label(base)
            rows.append([InlineKeyboardButton(text=text, callback_data=f"targets:toggle:{pos}")])
            continue
        if pos in taken_positions:
            continue
        rows.append([InlineKeyboardButton(text=target_label(base), callback_data=f"targets:claim:{pos}")])
    if not rows:
        rows.append([InlineKeyboardButton(text=label("no_targets"), callback_data="targets:none")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def targets_admin_action_kb(position: int, has_claim: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="✅ Назначить игроку", callback_data=f"targets:admin-assign:{position}")]]
    if has_claim:
        rows.append(
            [InlineKeyboardButton(text="🗑 Освободить цель", callback_data=f"targets:admin-release:{position}")]
        )
    rows.append(
        [InlineKeyboardButton(text="⬅️ Назад к списку целей", callback_data="targets:admin-back")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def targets_admin_members_kb(
    members: list[dict],
    position: int,
    page: int,
    page_size: int = 10,
) -> InlineKeyboardMarkup:
    page = max(page, 1)
    start = (page - 1) * page_size
    end = start + page_size
    rows: list[list[InlineKeyboardButton]] = []
    for member in members[start:end]:
        name = short_name(member.get("name"))
        th = member.get("townhallLevel")
        map_pos = member.get("mapPosition")
        tag = member.get("tag") or ""
        th_label = f"TH{th}" if th else ""
        pos_label = f"#{map_pos} " if map_pos else ""
        text = f"{pos_label}{th_label} · {name}".strip(" ·")
        rows.append([InlineKeyboardButton(text=text, callback_data=f"targets:admin-pick:{position}:{tag}")])
    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(text="◀️", callback_data=f"targets:admin-page:{position}:{page - 1}")
        )
    if end < len(members):
        nav_row.append(
            InlineKeyboardButton(text="▶️", callback_data=f"targets:admin-page:{position}:{page + 1}")
        )
    if nav_row:
        rows.append(nav_row)
    rows.append(
        [InlineKeyboardButton(text="⬅️ Назад к цели", callback_data=f"targets:admin-select:{position}")]
    )
    if not rows:
        rows.append([InlineKeyboardButton(text=label("no_targets"), callback_data="targets:none")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
