"""Lightweight SQLite availability probe for local readiness checks."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mabrid.server.logging import get_logger

logger = get_logger(__name__)


class SqliteReadinessProbe:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def is_ready(self) -> bool:
        try:
            async with self._session_factory() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            logger.warning("SQLite readiness probe failed", exc_info=True)
            return False
        return True
