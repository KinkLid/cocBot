from __future__ import annotations

from aiogram.fsm.context import FSMContext


async def set_menu(state: FSMContext, menu: str) -> None:
    data = await state.get_data()
    stack = list(data.get("menu_stack", []))
    if not stack or stack[-1] != menu:
        stack.append(menu)
    await state.update_data(menu_stack=stack)


async def pop_menu(state: FSMContext) -> str | None:
    data = await state.get_data()
    stack = list(data.get("menu_stack", []))
    if not stack:
        return None
    stack.pop()
    await state.update_data(menu_stack=stack)
    return stack[-1] if stack else None


async def reset_menu(state: FSMContext) -> None:
    await state.update_data(menu_stack=[])
