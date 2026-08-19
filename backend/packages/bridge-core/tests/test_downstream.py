from __future__ import annotations

from typing import Any, cast

import pytest
from starlette.types import Message, Receive, Scope, Send

from mcp_bridge_core import (
    AppResource,
    BridgeDownstreamServer,
    NoOpBridgeObserver,
    ResourceDescriptor,
    ToolCallResult,
    ToolDescriptor,
    UpstreamIdentity,
)
from mcp_bridge_core.handlers import ProxyHandlers


class EmptyRouter:
    async def list_tools(self) -> list[ToolDescriptor]:
        return []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        return ToolCallResult()

    async def preload_tool_resource(self, tool_name: str) -> None:
        return None

    async def list_resources(self) -> list[ResourceDescriptor]:
        return []

    async def read_resource(self, uri: str) -> AppResource:
        return AppResource(uri=uri, mime_type="text/plain", text="fixture")


class RecordingSseTransport:
    def __init__(self) -> None:
        self.scope: Scope | None = None

    async def handle_post_message(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.scope = scope


def create_downstream(identity: UpstreamIdentity) -> BridgeDownstreamServer:
    handlers = ProxyHandlers(EmptyRouter(), NoOpBridgeObserver(), "session-1")
    return BridgeDownstreamServer(
        handlers,
        identity_provider=lambda: identity,
        name="Fallback Name",
        version="0.1.0",
    )


def test_downstream_initialization_uses_public_identity() -> None:
    downstream = create_downstream(
        UpstreamIdentity(
            server_name="Fixture MCP",
            server_version="1.2.3",
            instructions="Use fixture tools.",
        )
    )

    options = downstream._create_initialization_options("Fallback instructions.")

    assert options.server_name == "Fixture MCP"
    assert options.server_version == "1.2.3"
    assert options.instructions == "Use fixture tools."
    assert options.capabilities.tools is not None
    assert options.capabilities.resources is not None


async def test_downstream_normalizes_legacy_sse_session_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downstream = create_downstream(UpstreamIdentity(server_name="Fixture MCP"))
    transport = RecordingSseTransport()
    monkeypatch.setattr(downstream, "_sse_transport", transport)

    async def receive() -> Message:
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        return None

    scope = cast(Scope, {"type": "http", "query_string": b"sessionId=fixture"})
    await downstream.handle_sse_post(scope, receive, send)

    assert transport.scope is not None
    assert transport.scope["query_string"] == b"session_id=fixture"
