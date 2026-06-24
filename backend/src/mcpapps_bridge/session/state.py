"""In-memory single-session state for the early bridge runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import anyio

from mcpapps_bridge.events import (
    AppResourceLoadedEvent,
    ErrorRaisedEvent,
    SessionEvent,
    SessionStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
    ToolDiscoveredEvent,
)
from mcpapps_bridge.models import (
    AppResource,
    BridgeSessionSnapshot,
    SessionStatus,
    ToolCallRecord,
    ToolCallResult,
    ToolCallStatus,
    ToolDescriptor,
    UpstreamInitialization,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BridgeSessionState:
    def __init__(self, session_id: str):
        self._lock = anyio.Lock()
        self._snapshot = BridgeSessionSnapshot(session_id=session_id)
        self._events: list[SessionEvent] = []
        self._tools: dict[str, ToolDescriptor] = {}
        self._active_tool_calls: dict[str, ToolCallRecord] = {}
        self._resources: dict[str, AppResource] = {}

    async def start(self, upstream: UpstreamInitialization | None = None) -> SessionStartedEvent:
        async with self._lock:
            self._snapshot.status = SessionStatus.READY
            self._snapshot.upstream = upstream
            self._snapshot.updated_at = utc_now()
            event = SessionStartedEvent(session_id=self._snapshot.session_id, upstream=upstream)
            self._append_event(event)
            return event

    async def register_tools(self, tools: list[ToolDescriptor]) -> list[ToolDiscoveredEvent]:
        async with self._lock:
            events: list[ToolDiscoveredEvent] = []
            for tool in tools:
                self._tools[tool.name] = tool
                event = ToolDiscoveredEvent(session_id=self._snapshot.session_id, tool=tool)
                self._append_event(event)
                events.append(event)
            self._snapshot.discovered_tools = list(self._tools.values())
            self._snapshot.updated_at = utc_now()
            return events

    async def start_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, object] | None = None,
    ) -> ToolCallStartedEvent:
        async with self._lock:
            call = ToolCallRecord(
                call_id=str(uuid4()),
                tool_name=tool_name,
                arguments=dict(arguments or {}),
                status=ToolCallStatus.RUNNING,
            )
            self._active_tool_calls[call.call_id] = call
            self._snapshot.active_tool_calls = list(self._active_tool_calls.values())
            self._snapshot.updated_at = utc_now()
            event = ToolCallStartedEvent(session_id=self._snapshot.session_id, call=call)
            self._append_event(event)
            return event

    async def complete_tool_call(
        self,
        call_id: str,
        result: ToolCallResult,
        *,
        failed: bool = False,
    ) -> ToolCallCompletedEvent:
        async with self._lock:
            if call_id not in self._active_tool_calls:
                raise KeyError(f"Unknown active tool call: {call_id}")
            call = self._active_tool_calls.pop(call_id)
            call.status = ToolCallStatus.FAILED if failed or result.is_error else ToolCallStatus.COMPLETED
            call.result = result
            call.completed_at = utc_now()
            self._snapshot.active_tool_calls = list(self._active_tool_calls.values())
            self._snapshot.updated_at = utc_now()
            event = ToolCallCompletedEvent(session_id=self._snapshot.session_id, call=call)
            self._append_event(event)
            return event

    async def load_resource(self, resource: AppResource) -> AppResourceLoadedEvent:
        async with self._lock:
            self._resources[resource.uri] = resource
            self._snapshot.loaded_resources = list(self._resources.values())
            self._snapshot.updated_at = utc_now()
            event = AppResourceLoadedEvent(session_id=self._snapshot.session_id, resource=resource)
            self._append_event(event)
            return event

    async def record_error(
        self,
        message: str,
        details: dict[str, object] | None = None,
    ) -> ErrorRaisedEvent:
        async with self._lock:
            self._snapshot.status = SessionStatus.ERROR
            self._snapshot.last_error = message
            self._snapshot.updated_at = utc_now()
            event = ErrorRaisedEvent(
                session_id=self._snapshot.session_id,
                message=message,
                details=dict(details or {}),
            )
            self._append_event(event)
            return event

    async def snapshot(self) -> BridgeSessionSnapshot:
        async with self._lock:
            return self._snapshot.model_copy(deep=True)

    async def events(self, after_index: int = 0) -> list[SessionEvent]:
        async with self._lock:
            return [event.model_copy(deep=True) for event in self._events[after_index:]]

    def _append_event(self, event: SessionEvent) -> None:
        self._events.append(event)
        self._snapshot.event_count = len(self._events)
