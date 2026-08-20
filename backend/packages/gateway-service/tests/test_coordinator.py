from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from mcp_bridge_core import (
    AppResource,
    ResourceDescriptor,
    ToolCallResult,
    ToolDescriptor,
    UpstreamConfig,
    UpstreamIdentity,
)
from mcp_gateway_service import (
    BridgeSessionRecord,
    BridgeSessionStatus,
    BridgeSessionStore,
    BridgeSessionStoreFactory,
    EndpointBindingRevision,
    EndpointRepository,
    EndpointTopologyRevision,
    GatewaySessionCoordinator,
    StdioConnection,
    UpstreamRevision,
    UpstreamServerRepository,
)


class FailingClient:
    async def connect(self, config: UpstreamConfig) -> UpstreamIdentity:
        raise RuntimeError("fixture upstream is offline")

    async def list_tools(self) -> list[ToolDescriptor]:
        return []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        return ToolCallResult()

    async def list_resources(self) -> list[ResourceDescriptor]:
        return []

    async def read_resource(self, uri: str) -> AppResource:
        return AppResource(uri=uri, mime_type="text/plain", text="")

    async def close(self) -> None:
        return None


class FailingClientFactory:
    def create(self, config: UpstreamConfig) -> FailingClient:
        return FailingClient()


class SingleTopologyReader:
    def __init__(self, revision: EndpointTopologyRevision) -> None:
        self.revision = revision

    async def list_current_revisions(self) -> list[EndpointTopologyRevision]:
        return [self.revision]

    async def resolve_current_revision(self, endpoint_slug: str) -> EndpointTopologyRevision | None:
        return self.revision if endpoint_slug == self.revision.slug else None

    async def get_revision(self, revision_id: UUID) -> EndpointTopologyRevision | None:
        return self.revision if revision_id == self.revision.revision_id else None


class MemorySessionRepository:
    def __init__(self) -> None:
        self.records: dict[UUID, BridgeSessionRecord] = {}

    async def add(self, session: BridgeSessionRecord) -> None:
        self.records[session.session_id] = session.model_copy(deep=True)

    async def update(self, session: BridgeSessionRecord) -> None:
        self.records[session.session_id] = session.model_copy(deep=True)

    async def get(self, session_id: UUID) -> BridgeSessionRecord | None:
        return self.records.get(session_id)

    async def get_by_transport_session_id(
        self, transport_session_id: str
    ) -> BridgeSessionRecord | None:
        return next(
            (
                record
                for record in self.records.values()
                if record.downstream_transport_session_id == transport_session_id
            ),
            None,
        )

    async def list(self, endpoint_id: UUID | None = None) -> list[BridgeSessionRecord]:
        return [
            record
            for record in self.records.values()
            if endpoint_id is None or record.endpoint_id == endpoint_id
        ]


class MemoryStoreFactory:
    async def create(self, session_id: UUID) -> BridgeSessionStore:
        return cast(BridgeSessionStore, object())

    async def get(self, session_id: UUID) -> BridgeSessionStore | None:
        return cast(BridgeSessionStore, object())

    async def remove(self, session_id: UUID) -> None:
        return None


async def test_coordinator_marks_session_failed_when_core_session_cannot_start() -> None:
    upstream = UpstreamRevision(
        server_id=uuid4(),
        slug="fixture",
        display_name="Fixture",
        connection=StdioConnection(command="fixture-server"),
    )
    revision = EndpointTopologyRevision(
        endpoint_id=uuid4(),
        slug="fixture",
        display_name="Fixture",
        bindings=(EndpointBindingRevision(upstream=upstream),),
    )
    sessions = MemorySessionRepository()
    coordinator = GatewaySessionCoordinator(
        cast(UpstreamServerRepository, object()),
        cast(EndpointRepository, object()),
        SingleTopologyReader(revision),
        sessions,
        cast(BridgeSessionStoreFactory, MemoryStoreFactory()),
        upstream_client_factory=FailingClientFactory(),
    )
    await coordinator.load_published_endpoints()

    async with coordinator.lifecycle():
        with pytest.raises(RuntimeError, match="Failed to connect to upstream MCP server"):
            await coordinator.open_session("fixture")

    [record] = await sessions.list()
    assert record.status is BridgeSessionStatus.FAILED
    assert record.error_message is not None
    assert record.error_message.startswith("Failed to connect to upstream MCP server")
