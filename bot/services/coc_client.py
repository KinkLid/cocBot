from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CocClient:
    base_url: str
    token: str

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers=self._headers(), params=params)
        if response.status_code == 403:
            logger.warning("CoC API forbidden for %s", path)
        if response.status_code == 429:
            logger.warning("CoC API rate limit hit for %s", path)
        response.raise_for_status()
        return response.json()

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, headers=self._headers(), json=payload)
        if response.status_code == 403:
            logger.warning("CoC API forbidden for %s", path)
        if response.status_code == 429:
            logger.warning("CoC API rate limit hit for %s", path)
        response.raise_for_status()
        return response.json()

    async def verify_token(self, player_tag: str, token: str) -> bool:
        payload = {"token": token}
        data = await self._post(f"/players/{quote(player_tag)}/verifytoken", payload)
        return data.get("status") == "ok"

    async def get_player(self, player_tag: str) -> dict[str, Any]:
        return await self._get(f"/players/{quote(player_tag)}")

    async def get_clan(self, clan_tag: str) -> dict[str, Any]:
        return await self._get(f"/clans/{quote(clan_tag)}")

    async def get_clan_members(self, clan_tag: str) -> dict[str, Any]:
        return await self._get(f"/clans/{quote(clan_tag)}/members")

    async def get_current_war(self, clan_tag: str) -> dict[str, Any]:
        return await self._get(f"/clans/{quote(clan_tag)}/currentwar")

    async def get_league_group(self, clan_tag: str) -> dict[str, Any]:
        return await self._get(f"/clans/{quote(clan_tag)}/currentwar/leaguegroup")

    async def get_cwl_war(self, war_tag: str) -> dict[str, Any]:
        return await self._get(f"/clanwarleagues/wars/{quote(war_tag)}")

    async def get_warlog(self, clan_tag: str) -> dict[str, Any]:
        return await self._get(f"/clans/{quote(clan_tag)}/warlog")

    async def get_capital_raid_seasons(self, clan_tag: str) -> dict[str, Any]:
        return await self._get(f"/clans/{quote(clan_tag)}/capitalraidseasons")
