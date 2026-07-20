"""Persistent bridge session event and snapshot storage."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypeVar
from uuid import UUID, uuid4

import anyio
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mcpapps_bridge.events import (
    AppResourceLoadedEvent,
    ErrorRaisedEvent,
    SessionEvent,
    SessionStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
    ToolDiscoveredEvent,
    UpstreamAvailabilityChangedEvent,
)
from mcpapps_bridge.models import (
    AppResource,
    BridgeSessionSnapshot,
    SessionStatus,
    ToolCallRecord,
    ToolCallResult,
    ToolCallStatus,
    ToolDescriptor,
    UpstreamAvailability,
    UpstreamAvailabilityStatus,
    UpstreamInitialization,
)
from mcpapps_bridge.session import BridgeSessionStore

from .models import BridgeSessionRow, SessionEventRow, SessionSnapshotRow

EVENT_ADAPTER = TypeAdapter(SessionEvent)
EventType = TypeVar("EventType", bound=SessionEvent)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SqlAlchemyBridgeSessionStore:
    def __init__(
        self,
        session_id: UUID,
        session_factory: async_sessionmaker[AsyncSession],
        next_event: anyio.Event,
    ) -> None:
        self._session_id = session_id
        self._session_factory = session_factory
        self._lock = anyio.Lock()
        self._next_event = next_event

    async def start(
        self,
        upstream: UpstreamInitialization | None = None,
    ) -> SessionStartedEvent:
        def mutate(snapshot: BridgeSessionSnapshot) -> SessionStartedEvent:
            snapshot.status = SessionStatus.READY
            snapshot.upstream = upstream
            return SessionStartedEvent(session_id=str(self._session_id), upstream=upstream)

        return await self._mutate(mutate)

    async def register_tools(self, tools: list[ToolDescriptor]) -> list[ToolDiscoveredEvent]:
        async with self._lock:
            async with self._session_factory.begin() as session:
                snapshot = await self._load_snapshot(session)
                tool_index = {tool.name: tool for tool in snapshot.discovered_tools}
                events: list[ToolDiscoveredEvent] = []
                for tool in tools:
                    tool_index[tool.name] = tool
                    event = ToolDiscoveredEvent(session_id=str(self._session_id), tool=tool)
                    await self._append_event(session, snapshot, event)
                    events.append(event)
                snapshot.discovered_tools = list(tool_index.values())
                await self._save_snapshot(session, snapshot)
            self._notify_waiters()
            return events

    async def start_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, object] | None = None,
    ) -> ToolCallStartedEvent:
        def mutate(snapshot: BridgeSessionSnapshot) -> ToolCallStartedEvent:
            call = ToolCallRecord(
                call_id=str(uuid4()),
                tool_name=tool_name,
                arguments=dict(arguments or {}),
                status=ToolCallStatus.RUNNING,
            )
            snapshot.active_tool_calls.append(call)
            return ToolCallStartedEvent(session_id=str(self._session_id), call=call)

        return await self._mutate(mutate)

    async def complete_tool_call(
        self,
        call_id: str,
        result: ToolCallResult,
        *,
        failed: bool = False,
    ) -> ToolCallCompletedEvent:
        def mutate(snapshot: BridgeSessionSnapshot) -> ToolCallCompletedEvent:
            call = next(
                (item for item in snapshot.active_tool_calls if item.call_id == call_id),
                None,
            )
            if call is None:
                raise KeyError(f"Unknown active tool call: {call_id}")
            snapshot.active_tool_calls = [
                item for item in snapshot.active_tool_calls if item.call_id != call_id
            ]
            call.status = (
                ToolCallStatus.FAILED if failed or result.is_error else ToolCallStatus.COMPLETED
            )
            call.result = result
            call.completed_at = utc_now()
            return ToolCallCompletedEvent(session_id=str(self._session_id), call=call)

        return await self._mutate(mutate)

    async def load_resource(self, resource: AppResource) -> AppResourceLoadedEvent:
        def mutate(snapshot: BridgeSessionSnapshot) -> AppResourceLoadedEvent:
            resource_index = {item.uri: item for item in snapshot.loaded_resources}
            resource_index[resource.uri] = resource
            snapshot.loaded_resources = list(resource_index.values())
            return AppResourceLoadedEvent(session_id=str(self._session_id), resource=resource)

        return await self._mutate(mutate)

    async def set_upstream_availability(
        self,
        availability: list[UpstreamAvailability],
    ) -> list[UpstreamAvailabilityChangedEvent]:
        async with self._lock:
            async with self._session_factory.begin() as session:
                snapshot = await self._load_snapshot(session)
                previous = {
                    item.binding_revision_id: item for item in snapshot.upstream_availability
                }
                current = {item.binding_revision_id: item for item in availability}
                events: list[UpstreamAvailabilityChangedEvent] = []
                for binding_revision_id, item in current.items():
                    if previous.get(binding_revision_id) == item:
                        continue
                    event = UpstreamAvailabilityChangedEvent(
                        session_id=str(self._session_id),
                        availability=item,
                    )
                    await self._append_event(session, snapshot, event)
                    events.append(event)
                snapshot.upstream_availability = list(current.values())
                statuses = {item.status for item in availability}
                if UpstreamAvailabilityStatus.AVAILABLE in statuses:
                    snapshot.status = (
                        SessionStatus.DEGRADED
                        if UpstreamAvailabilityStatus.FAILED in statuses
                        else SessionStatus.READY
                    )
                elif availability and statuses == {UpstreamAvailabilityStatus.FAILED}:
                    snapshot.status = SessionStatus.ERROR
                await self._save_snapshot(session, snapshot)
            if events:
                self._notify_waiters()
            return events

    async def record_error(
        self,
        message: str,
        details: dict[str, object] | None = None,
    ) -> ErrorRaisedEvent:
        def mutate(snapshot: BridgeSessionSnapshot) -> ErrorRaisedEvent:
            snapshot.status = SessionStatus.ERROR
            snapshot.last_error = message
            return ErrorRaisedEvent(
                session_id=str(self._session_id),
                message=message,
                details=dict(details or {}),
            )

        return await self._mutate(mutate)

    async def snapshot(self) -> BridgeSessionSnapshot:
        async with self._session_factory() as session:
            return await self._load_snapshot(session)

    async def events(self, after_index: int = 0) -> list[SessionEvent]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(SessionEventRow)
                    .where(
                        SessionEventRow.session_id == self._session_id,
                        SessionEventRow.sequence > after_index,
                    )
                    .order_by(SessionEventRow.sequence)
                )
            ).all()
            return [EVENT_ADAPTER.validate_python(row.payload_json) for row in rows]

    async def wait_for_events(self, after_index: int = 0) -> list[SessionEvent]:
        while True:
            async with self._lock:
                events = await self.events(after_index)
                if events:
                    return events
                next_event = self._next_event
            await next_event.wait()

    async def _mutate(
        self,
        mutation: Callable[[BridgeSessionSnapshot], EventType],
    ) -> EventType:
        async with self._lock:
            async with self._session_factory.begin() as session:
                snapshot = await self._load_snapshot(session)
                event = mutation(snapshot)
                await self._append_event(session, snapshot, event)
                await self._save_snapshot(session, snapshot)
            self._notify_waiters()
            return event

    async def _load_snapshot(self, session: AsyncSession) -> BridgeSessionSnapshot:
        row = await session.get(SessionSnapshotRow, self._session_id)
        if row is None:
            return BridgeSessionSnapshot(session_id=str(self._session_id))
        return BridgeSessionSnapshot.model_validate(row.payload_json)

    async def _append_event(
        self,
        session: AsyncSession,
        snapshot: BridgeSessionSnapshot,
        event: SessionEvent,
    ) -> None:
        snapshot.event_count += 1
        snapshot.updated_at = utc_now()
        session.add(
            SessionEventRow(
                event_id=UUID(event.event_id),
                session_id=self._session_id,
                sequence=snapshot.event_count,
                kind=event.kind,
                payload_json=event.model_dump(mode="json"),
                created_at=event.created_at,
            )
        )

    async def _save_snapshot(
        self,
        session: AsyncSession,
        snapshot: BridgeSessionSnapshot,
    ) -> None:
        snapshot.updated_at = utc_now()
        row = await session.get(SessionSnapshotRow, self._session_id)
        if row is None:
            session.add(
                SessionSnapshotRow(
                    session_id=self._session_id,
                    status=snapshot.status.value,
                    event_count=snapshot.event_count,
                    payload_json=snapshot.model_dump(mode="json"),
                    updated_at=snapshot.updated_at,
                )
            )
            return
        row.status = snapshot.status.value
        row.event_count = snapshot.event_count
        row.payload_json = snapshot.model_dump(mode="json")
        row.updated_at = snapshot.updated_at

    def _notify_waiters(self) -> None:
        waiter = self._next_event
        self._next_event = anyio.Event()
        waiter.set()


class SqlAlchemyBridgeSessionStoreFactory:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._stores: dict[UUID, SqlAlchemyBridgeSessionStore] = {}
        self._lock = anyio.Lock()

    async def create(self, session_id: UUID) -> BridgeSessionStore:
        async with self._lock:
            if session_id in self._stores:
                raise ValueError(f"Session store already exists: {session_id}")
            return self._create_store(session_id)

    async def get(self, session_id: UUID) -> BridgeSessionStore | None:
        async with self._lock:
            store = self._stores.get(session_id)
            if store is not None:
                return store
            async with self._session_factory() as session:
                exists = await session.get(BridgeSessionRow, session_id)
            return self._create_store(session_id) if exists is not None else None

    async def remove(self, session_id: UUID) -> None:
        async with self._lock:
            self._stores.pop(session_id, None)

    def _create_store(self, session_id: UUID) -> SqlAlchemyBridgeSessionStore:
        store = SqlAlchemyBridgeSessionStore(
            session_id,
            self._session_factory,
            anyio.Event(),
        )
        self._stores[session_id] = store
        return store
