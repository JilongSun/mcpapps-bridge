"""Session store interface used by bridge runtime components."""

from __future__ import annotations

from typing import Protocol

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
    ToolCallResult,
    ToolDescriptor,
    UpstreamAvailability,
    UpstreamInitialization,
)


class BridgeSessionStore(Protocol):
    async def start(
        self, upstream: UpstreamInitialization | None = None
    ) -> SessionStartedEvent: ...

    async def register_tools(self, tools: list[ToolDescriptor]) -> list[ToolDiscoveredEvent]: ...

    async def start_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, object] | None = None,
    ) -> ToolCallStartedEvent: ...

    async def complete_tool_call(
        self,
        call_id: str,
        result: ToolCallResult,
        *,
        failed: bool = False,
    ) -> ToolCallCompletedEvent: ...

    async def load_resource(self, resource: AppResource) -> AppResourceLoadedEvent: ...

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
