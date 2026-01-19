from __future__ import annotations

from bot.services.coc_client import CocClient


async def find_current_cwl_war(coc_client: CocClient, clan_tag: str) -> dict | None:
    try:
        league = await coc_client.get_league_group(clan_tag)
    except Exception:  # noqa: BLE001
        return None
    for round_item in league.get("rounds", []):
        for tag in round_item.get("warTags", []):
            if tag and tag != "#0":
                try:
                    war = await coc_client.get_cwl_war(tag)
                except Exception:  # noqa: BLE001
                    continue
                if war.get("state") in {"preparation", "inWar"}:
                    return war
    return None


async def get_missed_attacks_label(coc_client: CocClient, clan_tag: str) -> str | None:
    cwl_war = await find_current_cwl_war(coc_client, clan_tag)
    if cwl_war:
        return "📋 Кто не атаковал (ЛВК текущая война)"
    try:
        war_data = await coc_client.get_current_war(clan_tag)
    except Exception:  # noqa: BLE001
        return None
    if war_data.get("state") in {"preparation", "inWar"}:
        return "📋 Кто не атаковал (КВ сейчас)"
    return None
