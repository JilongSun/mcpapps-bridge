"""SQLite reader for persisted session snapshots and sequenced events."""

from __future__ import annotations

from uuid import UUID

from mabrid.application.gateway.inspection import (
    BridgeSessionSnapshot,
    SessionEvent,
    SessionEventPage,
    SessionEventPageRequest,
    SequencedSessionEvent,
)
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..schema import BridgeSessionRow, SessionEventRow, SessionSnapshotRow

EVENT_ADAPTER = TypeAdapter(SessionEvent)


class SqlAlchemySessionInspectionReader:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_snapshot(self, session_id: UUID) -> BridgeSessionSnapshot | None:
        async with self._session_factory() as session:
            if await session.get(BridgeSessionRow, session_id) is None:
                return None
            row = await session.get(SessionSnapshotRow, session_id)
        if row is None:
            return BridgeSessionSnapshot(session_id=str(session_id))
        return BridgeSessionSnapshot.model_validate(row.payload_json)

    async def list_events(
        self,
        request: SessionEventPageRequest,
    ) -> SessionEventPage | None:
        async with self._session_factory() as session:
            if await session.get(BridgeSessionRow, request.session_id) is None:
                return None
            rows = list(
                await session.scalars(
                    select(SessionEventRow)
                    .where(
                        SessionEventRow.session_id == request.session_id,
                        SessionEventRow.sequence > request.after,
                    )
                    .order_by(SessionEventRow.sequence)
                    .limit(request.limit + 1)
                )
            )
        has_more = len(rows) > request.limit
        items = tuple(
            SequencedSessionEvent(
                sequence=row.sequence,
                event=EVENT_ADAPTER.validate_python(row.payload_json),
            )
            for row in rows[: request.limit]
        )
        return SessionEventPage(
            items=items,
            next_after=items[-1].sequence if has_more else None,
        )
