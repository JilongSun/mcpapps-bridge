"""SQLite implementation of durable Agent Session and unresolved execution ports."""

from datetime import timezone
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mabrid.application.agent_host import (
    AgentSessionRecord,
    RuntimeRunHandle,
    RuntimeSessionReference,
    UnsettledSessionRun,
)

from .schema import AgentSessionRow, UnsettledAgentRunRow


class SqliteAgentSessionRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add(self, session: AgentSessionRecord) -> None:
        async with self._sessions.begin() as transaction:
            transaction.add(
                AgentSessionRow(
                    session_id=session.session_id,
                    target_id=session.target_id,
                    runtime_binding_id=session.runtime_session.runtime_binding_id,
                    remote_session_id=session.runtime_session.remote_session_id,
                    title=session.title,
                    created_at=session.created_at,
                )
            )

    async def get(self, session_id: UUID) -> AgentSessionRecord | None:
        async with self._sessions() as transaction:
            row = await transaction.get(AgentSessionRow, session_id)
            return _record(row) if row is not None else None

    async def list_sessions(
        self, *, target_id: str, limit: int, offset: int
    ) -> tuple[AgentSessionRecord, ...]:
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError("Invalid Agent Session pagination")
        async with self._sessions() as transaction:
            rows = await transaction.scalars(
                select(AgentSessionRow)
                .where(AgentSessionRow.target_id == target_id)
                .order_by(AgentSessionRow.created_at.desc(), AgentSessionRow.session_id)
                .limit(limit)
                .offset(offset)
            )
            return tuple(_record(row) for row in rows)

    async def update_runtime_session(
        self,
        session_id: UUID,
        *,
        expected: RuntimeSessionReference,
        replacement: RuntimeSessionReference,
    ) -> bool:
        if replacement.runtime_binding_id != expected.runtime_binding_id:
            raise ValueError("Agent Session cannot migrate to another runtime deployment")
        async with self._sessions.begin() as transaction:
            result = await transaction.execute(
                update(AgentSessionRow)
                .where(
                    AgentSessionRow.session_id == session_id,
                    AgentSessionRow.runtime_binding_id == expected.runtime_binding_id,
                    AgentSessionRow.remote_session_id == expected.remote_session_id,
                )
                .values(remote_session_id=replacement.remote_session_id)
                .returning(AgentSessionRow.session_id)
            )
            return result.scalar_one_or_none() is not None

    async def get_unsettled_run(self, target_id: str) -> UnsettledSessionRun | None:
        async with self._sessions() as transaction:
            row = await transaction.get(UnsettledAgentRunRow, target_id)
            if row is None:
                return None
            return UnsettledSessionRun(
                target_id=row.target_id,
                session_id=row.session_id,
                run_id=row.run_id,
                runtime_binding_id=row.runtime_binding_id,
                remote_run_id=row.remote_run_id,
            )

    async def claim_run(self, session: AgentSessionRecord, run_id: UUID) -> bool:
        try:
            async with self._sessions.begin() as transaction:
                transaction.add(
                    UnsettledAgentRunRow(
                        target_id=session.target_id,
                        session_id=session.session_id,
                        run_id=run_id,
                        runtime_binding_id=session.runtime_session.runtime_binding_id,
                    )
                )
        except IntegrityError:
            return False
        return True

    async def record_runtime_run(
        self, target_id: str, run_id: UUID, handle: RuntimeRunHandle
    ) -> None:
        async with self._sessions.begin() as transaction:
            result = await transaction.execute(
                update(UnsettledAgentRunRow)
                .where(
                    UnsettledAgentRunRow.target_id == target_id,
                    UnsettledAgentRunRow.run_id == run_id,
                    UnsettledAgentRunRow.runtime_binding_id == handle.runtime_binding_id,
                )
                .values(remote_run_id=handle.remote_run_id)
                .returning(UnsettledAgentRunRow.run_id)
            )
            if result.scalar_one_or_none() is None:
                raise RuntimeError("Unsettled Run does not belong to the provided runtime handle")

    async def release_run(self, target_id: str, run_id: UUID) -> None:
        async with self._sessions.begin() as transaction:
            result = await transaction.execute(
                delete(UnsettledAgentRunRow)
                .where(
                    UnsettledAgentRunRow.target_id == target_id,
                    UnsettledAgentRunRow.run_id == run_id,
                )
                .returning(UnsettledAgentRunRow.run_id)
            )
            if result.scalar_one_or_none() is None:
                raise RuntimeError("Cannot release another Agent Run")


def _record(row: AgentSessionRow) -> AgentSessionRecord:
    return AgentSessionRecord(
        session_id=row.session_id,
        target_id=row.target_id,
        runtime_session=RuntimeSessionReference(
            runtime_binding_id=row.runtime_binding_id, remote_session_id=row.remote_session_id
        ),
        title=row.title,
        created_at=row.created_at.replace(tzinfo=timezone.utc)
        if row.created_at.tzinfo is None
        else row.created_at,
    )
