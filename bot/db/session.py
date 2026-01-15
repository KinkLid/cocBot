from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker


def build_sessionmaker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)
