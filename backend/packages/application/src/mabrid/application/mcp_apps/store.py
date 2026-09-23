"""Process-local widget lifecycle event storage for the v0.1 Host workflow."""

from __future__ import annotations

from asyncio import Lock
from uuid import UUID

from .contracts import WidgetCreated, WidgetEvent


class InMemoryWidgetEventStore:
    def __init__(self) -> None:
        self._events: list[WidgetEvent] = []
        self._operation_keys: set[tuple[str, str]] = set()
        self._lock = Lock()

    async def append(self, event: WidgetEvent) -> None:
        key = _event_operation_key(event)
        async with self._lock:
            if key in self._operation_keys:
                raise ValueError(
                    f"Widget lifecycle already exists for Gateway tool operation: {key[0]}/{key[1]}"
                )
            self._operation_keys.add(key)
            self._events.append(event)

    async def list_for_run(self, run_id: UUID) -> tuple[WidgetEvent, ...]:
        async with self._lock:
            return tuple(event for event in self._events if _event_run_id(event) == run_id)


def _event_operation_key(event: WidgetEvent) -> tuple[str, str]:
    if isinstance(event, WidgetCreated):
        return event.widget.session_key, event.widget.operation_key
    return event.session_key, event.operation_key


def _event_run_id(event: WidgetEvent) -> UUID:
    return event.widget.run_id if isinstance(event, WidgetCreated) else event.run_id
