"""SQLAlchemy repository for persisted Gateway bridge session lifecycle records.

The repository stores application session history. It does not own live bridge runtimes, MCP
transport dispatch, or transport-session correlation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from mabrid.application.gateway.sessions import BridgeSessionRecord, BridgeSessionStatus
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..schema import BridgeSessionRow


class SqlAlchemyBridgeSessionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, session: BridgeSessionRecord) -> None:
        try:
            async with self._session_factory.begin() as db_session:
                db_session.add(_to_row(session))
        except IntegrityError as exc:
            raise ValueError(f"Bridge session already exists: {session.session_id}") from exc

    async def update(self, session: BridgeSessionRecord) -> None:
        async with self._session_factory.begin() as db_session:
            row = await db_session.get(BridgeSessionRow, session.session_id)
            if row is None:
                raise KeyError(f"Unknown bridge session: {session.session_id}")
            _update_row(row, session)

    async def get(self, session_id: UUID) -> BridgeSessionRecord | None:
        async with self._session_factory() as session:
            row = await session.get(BridgeSessionRow, session_id)
            return _from_row(row) if row is not None else None

    async def list(self, endpoint_id: UUID | None = None) -> list[BridgeSessionRecord]:
        statement = select(BridgeSessionRow).order_by(BridgeSessionRow.created_at.desc())
        if endpoint_id is not None:
            statement = statement.where(BridgeSessionRow.endpoint_id == endpoint_id)
        async with self._session_factory() as session:
            rows = (await session.scalars(statement)).all()
            return [_from_row(row) for row in rows]


def _to_row(session: BridgeSessionRecord) -> BridgeSessionRow:
    row = BridgeSessionRow(
        session_id=session.session_id,
        endpoint_id=session.endpoint_id,
        endpoint_revision_id=session.endpoint_revision_id,
    )
    _update_row(row, session)
    return row


def _update_row(row: BridgeSessionRow, session: BridgeSessionRecord) -> None:
    row.endpoint_id = session.endpoint_id
    row.endpoint_revision_id = session.endpoint_revision_id
    row.status = session.status.value
    row.created_at = session.created_at
    row.last_activity_at = session.last_activity_at
    row.closed_at = session.closed_at
    row.error_message = session.error_message


def _from_row(row: BridgeSessionRow) -> BridgeSessionRecord:
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
