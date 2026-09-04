"""Process-start recovery policy for interrupted persisted bridge sessions.

Live runtimes cannot survive a process restart, so non-terminal records are atomically marked
failed before new sessions are accepted.
"""

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..schema import BridgeSessionRow


async def mark_interrupted_sessions_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    now = datetime.now(timezone.utc)
    async with session_factory.begin() as session:
        interrupted_ids = list(
            await session.scalars(
                select(BridgeSessionRow.session_id).where(
                    BridgeSessionRow.status.in_(["starting", "active", "closing"])
                )
            )
        )
        if not interrupted_ids:
            return 0
        await session.execute(
            update(BridgeSessionRow)
            .where(BridgeSessionRow.session_id.in_(interrupted_ids))
            .values(
                status="failed",
                last_activity_at=now,
                closed_at=now,
                error_message="Gateway process restarted before the session closed",
            )
        )
        return len(interrupted_ids)
