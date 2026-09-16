"""SQLite reader for filtered and keyset-paginated session lifecycle history."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from mabrid.application.gateway.sessions import (
    BridgeSessionRecord,
    BridgeSessionStatus,
    SessionKeyset,
    SessionPage,
    SessionPageRequest,
)
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..schema import BridgeSessionRow


class SqlAlchemySessionHistoryReader:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_sessions(self, request: SessionPageRequest) -> SessionPage:
        statement = select(BridgeSessionRow)
        if request.endpoint_id is not None:
            statement = statement.where(BridgeSessionRow.endpoint_id == request.endpoint_id)
        if request.status is not None:
            statement = statement.where(BridgeSessionRow.status == request.status.value)
        if request.before is not None:
            statement = statement.where(
                or_(
                    BridgeSessionRow.created_at < request.before.created_at,
                    and_(
                        BridgeSessionRow.created_at == request.before.created_at,
                        BridgeSessionRow.session_id < request.before.session_id,
                    ),
                )
            )
        statement = statement.order_by(
            BridgeSessionRow.created_at.desc(),
            BridgeSessionRow.session_id.desc(),
        ).limit(request.limit + 1)

        async with self._session_factory() as session:
            rows = list(await session.scalars(statement))
        has_more = len(rows) > request.limit
        records = tuple(_session_from_row(row) for row in rows[: request.limit])
        next_keyset = None
        if has_more:
            last = records[-1]
            next_keyset = SessionKeyset(
                created_at=last.created_at,
                session_id=last.session_id,
            )
        return SessionPage(items=records, next_keyset=next_keyset)

    async def get_session(self, session_id: UUID) -> BridgeSessionRecord | None:
        async with self._session_factory() as session:
            row = await session.get(BridgeSessionRow, session_id)
        return _session_from_row(row) if row is not None else None


def _session_from_row(row: BridgeSessionRow) -> BridgeSessionRecord:
    return BridgeSessionRecord(
        session_id=row.session_id,
        endpoint_id=row.endpoint_id,
        endpoint_revision_id=row.endpoint_revision_id,
        status=BridgeSessionStatus(row.status),
        created_at=_as_utc(row.created_at),
        last_activity_at=_as_utc(row.last_activity_at),
        closed_at=_as_utc(row.closed_at) if row.closed_at is not None else None,
        error_message=row.error_message,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
