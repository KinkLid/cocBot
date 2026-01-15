from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def build_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, future=True, echo=False)
