"""Durable event and snapshot ports required by Gateway inspection projection."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .events import (
    ErrorRaisedEvent,
    ResourceReadEvent,
    SessionEvent,
    SessionStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
    ToolDiscoveredEvent,
    UpstreamAvailabilityChangedEvent,
)
from .models import (
    BridgeSessionSnapshot,
    ResourceReadRecord,
    ToolCallResult,
    ToolDescriptor,
    UpstreamAvailability,
    UpstreamInitialization,
)


class BridgeSessionStore(Protocol):
    async def start(
        self,
        upstream: UpstreamInitialization | None = None,
    ) -> SessionStartedEvent: ...

    async def register_tools(self, tools: list[ToolDescriptor]) -> list[ToolDiscoveredEvent]: ...

    async def start_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, object] | None = None,
        *,
        call_id: str | None = None,
    ) -> ToolCallStartedEvent: ...

    async def complete_tool_call(
        self,
        call_id: str,
        result: ToolCallResult,
        *,
        failed: bool = False,
    ) -> ToolCallCompletedEvent: ...

    async def record_resource_read(self, read: ResourceReadRecord) -> ResourceReadEvent: ...

    async def set_upstream_availability(
        self,
        availability: list[UpstreamAvailability],
    ) -> list[UpstreamAvailabilityChangedEvent]: ...

    async def record_error(
        self,
        message: str,
        details: dict[str, object] | None = None,
    ) -> ErrorRaisedEvent: ...

    async def snapshot(self) -> BridgeSessionSnapshot: ...

    async def events(self, after_index: int = 0) -> list[SessionEvent]: ...

    async def wait_for_events(self, after_index: int = 0) -> list[SessionEvent]: ...


class BridgeSessionStoreFactory(Protocol):
    async def create(self, session_id: UUID) -> BridgeSessionStore: ...

    async def get(self, session_id: UUID) -> BridgeSessionStore | None: ...

    async def remove(self, session_id: UUID) -> None: ...
