from __future__ import annotations

from aiogram.fsm.context import FSMContext


async def reset_state_if_any(state: FSMContext) -> None:
    if await state.get_state() is not None:
        await state.clear()
