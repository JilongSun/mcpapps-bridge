from __future__ import annotations

import json
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
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

from mcp_gateway_server.api import create_app


class FixtureClient:
    async def connect(self, config: UpstreamConfig) -> UpstreamIdentity:
        return UpstreamIdentity(
            server_name="Fixture MCP",
            server_version="1.0.0",
            protocol_version="2025-11-25",
            supports_tools=True,
            supports_resources=True,
        )

    async def list_tools(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                name="echo",
                description="Echo text",
                input_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                },
            )
        ]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        return ToolCallResult(content=({"type": "text", "text": str(arguments.get("text", ""))},))

    async def list_resources(self) -> list[ResourceDescriptor]:
        return [ResourceDescriptor(name="status", uri="data://status", mime_type="text/plain")]

    async def read_resource(self, uri: str) -> AppResource:
        return AppResource(uri=uri, mime_type="text/plain", text="ready")

    async def close(self) -> None:
        return None


class FixtureClientFactory:
    def create(self, config: UpstreamConfig) -> FixtureClient:
        return FixtureClient()


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
    def __init__(self) -> None:
        self.stores: dict[UUID, BridgeSessionStore] = {}

    async def create(self, session_id: UUID) -> BridgeSessionStore:
        store = cast(BridgeSessionStore, AsyncMock(spec=BridgeSessionStore))
        self.stores[session_id] = store
        return store

    async def get(self, session_id: UUID) -> BridgeSessionStore | None:
        return self.stores.get(session_id)

    async def remove(self, session_id: UUID) -> None:
        self.stores.pop(session_id, None)


def rpc_request(
    method: str, *, request_id: int | None = None, params: object = None
) -> dict[str, Any]:
    request: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        request["id"] = request_id
    if params is not None:
        request["params"] = params
    return request


def response_payload(response: httpx.Response) -> dict[str, Any]:
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        data = next(
            line.removeprefix("data: ")
            for line in response.text.splitlines()
            if line.startswith("data: ")
        )
        return cast(dict[str, Any], json.loads(data))
    return cast(dict[str, Any], response.json())


async def test_composed_server_supports_mcp_2025_streamable_http_contract() -> None:
    upstream = UpstreamRevision(
        server_id=uuid4(),
        slug="fixture",
        display_name="Fixture MCP",
        connection=StdioConnection(command="fixture-server"),
    )
    revision = EndpointTopologyRevision(
        endpoint_id=uuid4(),
        slug="fixture",
        display_name="Fixture MCP",
        bindings=(EndpointBindingRevision(upstream=upstream),),
    )
    sessions = MemorySessionRepository()
    coordinator = GatewaySessionCoordinator(
        cast(UpstreamServerRepository, object()),
        cast(EndpointRepository, object()),
        SingleTopologyReader(revision),
        sessions,
        cast(BridgeSessionStoreFactory, MemoryStoreFactory()),
        upstream_client_factory=FixtureClientFactory(),
    )
    await coordinator.load_published_endpoints()
    app = create_app(coordinator)
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
    }

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            initialized = await client.post(
                "/mcp/fixture",
                headers=headers,
                json=rpc_request(
                    "initialize",
                    request_id=1,
                    params={
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "contract-test", "version": "1.0.0"},
                    },
                ),
            )
            assert initialized.status_code == 200
            session_id = initialized.headers["mcp-session-id"]
            assert response_payload(initialized)["result"]["protocolVersion"] == "2025-11-25"

            session_headers = {**headers, "mcp-session-id": session_id}
            notification = await client.post(
                "/mcp/fixture",
                headers=session_headers,
                json=rpc_request("notifications/initialized"),
            )
            assert notification.status_code == 202

            tools = await client.post(
                "/mcp/fixture",
                headers=session_headers,
                json=rpc_request("tools/list", request_id=2, params={}),
            )
            assert response_payload(tools)["result"]["tools"][0]["name"] == "echo"

            called = await client.post(
                "/mcp/fixture",
                headers=session_headers,
                json=rpc_request(
                    "tools/call",
                    request_id=3,
                    params={"name": "echo", "arguments": {"text": "hello"}},
                ),
            )
            assert response_payload(called)["result"]["content"][0]["text"] == "hello"

            resources = await client.post(
                "/mcp/fixture",
                headers=session_headers,
                json=rpc_request("resources/list", request_id=4, params={}),
            )
            assert response_payload(resources)["result"]["resources"][0]["uri"] == "data://status"

            resource = await client.post(
                "/mcp/fixture",
                headers=session_headers,
                json=rpc_request(
                    "resources/read",
                    request_id=5,
                    params={"uri": "data://status"},
                ),
            )
            assert response_payload(resource)["result"]["contents"][0]["text"] == "ready"

            closed = await client.delete("/mcp/fixture", headers=session_headers)
            assert closed.status_code == 200

    [record] = await sessions.list()
    assert record.status is BridgeSessionStatus.CLOSED
