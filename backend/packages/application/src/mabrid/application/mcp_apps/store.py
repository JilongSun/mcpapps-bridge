"""Process-local widget lifecycle event storage for the v0.1 Host workflow."""

from __future__ import annotations

from asyncio import Condition
from uuid import UUID

from ..agent_host import OperationRunAttribution
from .contracts import WidgetCreated, WidgetEvent


class InMemoryWidgetEventStore:
    def __init__(self) -> None:
        self._events: list[WidgetEvent] = []
        self._operation_keys: set[tuple[str, str]] = set()
        self._pending_by_run: dict[UUID, set[tuple[str, str]]] = {}
        self._condition = Condition()

    async def start_operation(self, attribution: OperationRunAttribution) -> None:
        key = (attribution.session_key, attribution.operation_key)
        async with self._condition:
            pending = self._pending_by_run.setdefault(attribution.run_id, set())
            if key in pending:
                raise ValueError(f"Widget operation is already pending: {key[0]}/{key[1]}")
            pending.add(key)

    async def settle_operation(self, attribution: OperationRunAttribution) -> None:
        async with self._condition:
            self._settle(attribution.run_id, (attribution.session_key, attribution.operation_key))

    async def append(self, event: WidgetEvent) -> None:
        key = _event_operation_key(event)
        run_id = _event_run_id(event)
        async with self._condition:
            if key in self._operation_keys:
                raise ValueError(
                    f"Widget lifecycle already exists for Gateway tool operation: {key[0]}/{key[1]}"
                )
            self._operation_keys.add(key)
            self._events.append(event)
            self._settle(run_id, key)

    async def list_for_run(self, run_id: UUID) -> tuple[WidgetEvent, ...]:
        async with self._condition:
            return tuple(event for event in self._events if _event_run_id(event) == run_id)

    async def wait_until_settled(self, run_id: UUID) -> None:
        async with self._condition:
            await self._condition.wait_for(lambda: not self._pending_by_run.get(run_id))

    def _settle(self, run_id: UUID, key: tuple[str, str]) -> None:
        pending = self._pending_by_run.get(run_id)
        if pending is None:
            return
        pending.discard(key)
        if not pending:
            del self._pending_by_run[run_id]
            self._condition.notify_all()


def _event_operation_key(event: WidgetEvent) -> tuple[str, str]:
    if isinstance(event, WidgetCreated):
        return event.widget.session_key, event.widget.operation_key
    return event.session_key, event.operation_key


def _event_run_id(event: WidgetEvent) -> UUID:
    return event.widget.run_id if isinstance(event, WidgetCreated) else event.run_id
