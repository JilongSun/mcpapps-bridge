"""Persistence ports for managed topology, sessions, and inspection state."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .events import (
    AppResourceLoadedEvent,
    ErrorRaisedEvent,
    SessionEvent,
    SessionStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
    ToolDiscoveredEvent,
    UpstreamAvailabilityChangedEvent,
)
from .inspection import (
    AppResource,
    BridgeSessionSnapshot,
    ToolCallResult,
    ToolDescriptor,
    UpstreamAvailability,
    UpstreamInitialization,
)
from .management import EndpointDefinition, UpstreamServerDefinition
from .revisions import EndpointTopologyRevision
from .sessions import BridgeSessionRecord


class TopologyReader(Protocol):
    async def list_current_revisions(self) -> list[EndpointTopologyRevision]: ...

    async def resolve_current_revision(
        self, endpoint_slug: str
    ) -> EndpointTopologyRevision | None: ...

    async def get_revision(self, revision_id: UUID) -> EndpointTopologyRevision | None: ...


class UpstreamServerRepository(Protocol):
    async def add(self, server: UpstreamServerDefinition) -> None: ...

    async def get(self, server_id: UUID) -> UpstreamServerDefinition | None: ...

    async def list(self) -> list[UpstreamServerDefinition]: ...


class EndpointRepository(Protocol):
    async def add(self, endpoint: EndpointDefinition) -> None: ...

    async def get(self, endpoint_id: UUID) -> EndpointDefinition | None: ...

    async def get_by_slug(self, slug: str) -> EndpointDefinition | None: ...

    async def list(self) -> list[EndpointDefinition]: ...


class BridgeSessionRepository(Protocol):
    async def add(self, session: BridgeSessionRecord) -> None: ...

    async def update(self, session: BridgeSessionRecord) -> None: ...

    async def get(self, session_id: UUID) -> BridgeSessionRecord | None: ...

    async def get_by_transport_session_id(
        self, transport_session_id: str
    ) -> BridgeSessionRecord | None: ...

    async def list(self, endpoint_id: UUID | None = None) -> list[BridgeSessionRecord]: ...


class BridgeSessionStore(Protocol):
    async def start(
        self, upstream: UpstreamInitialization | None = None
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


class BridgeSessionStoreFactory(Protocol):
    async def create(self, session_id: UUID) -> BridgeSessionStore: ...

    async def get(self, session_id: UUID) -> BridgeSessionStore | None: ...

    async def remove(self, session_id: UUID) -> None: ...
