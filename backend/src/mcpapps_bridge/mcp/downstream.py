"""Downstream MCP server and transport hosting."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.types import Receive, Scope, Send

from mcpapps_bridge.session import BridgeSessionState

from .handlers import register_proxy_handlers
from .mapper import (
    to_mcp_call_tool_result,
    to_mcp_resource,
    to_mcp_tool,
    to_read_resource_contents,
)
from .runtime import BridgeRuntime


class BridgeDownstreamServer:
    """Hosts the downstream MCP protocol surface for one bridge runtime."""

    def __init__(
        self,
        runtime: BridgeRuntime,
        session_state: BridgeSessionState,
        *,
        name: str,
        version: str,
    ) -> None:
        self._runtime = runtime
        self._session_state = session_state
        self._version = version
        self._server = Server(name=name, version=version)
        self._sse_transport = SseServerTransport("/messages")
        self._streamable_http = StreamableHTTPSessionManager(app=self._server)
        self._register_handlers()

    async def start(self) -> None:
        await self._runtime.start()

    async def close(self) -> None:
        await self._runtime.close()

    async def serve_stdio(self) -> None:
        await self.start()
        try:
            async with stdio_server() as (read_stream, write_stream):
                await self._server.run(
                    read_stream,
                    write_stream,
                    self._create_initialization_options("Protocol-aware MCP Apps stdio proxy."),
                )
        finally:
            await self.close()

    @asynccontextmanager
    async def run_http_transports(self) -> AsyncIterator[None]:
        async with self._streamable_http.run():
            yield

    async def handle_streamable_http(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._streamable_http.handle_request(scope, receive, send)

    async def handle_sse(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.start()
        async with self._sse_transport.connect_sse(scope, receive, send) as streams:
            await self._server.run(
                streams[0],
                streams[1],
                self._create_initialization_options("Protocol-aware MCP Apps SSE proxy."),
            )

    async def handle_sse_post(self, scope: Scope, receive: Receive, send: Send) -> None:
        query_string = scope.get("query_string", b"")
        if b"sessionId=" in query_string and b"session_id=" not in query_string:
            scope = dict(scope)
            scope["query_string"] = query_string.replace(b"sessionId=", b"session_id=")
        await self._sse_transport.handle_post_message(scope, receive, send)

    def _create_initialization_options(self, instructions: str) -> InitializationOptions:
        identity = self._runtime.identity
        return InitializationOptions(
            server_name=identity.server_name,
            server_version=identity.server_version or self._version,
            capabilities=self._server.get_capabilities(NotificationOptions(), {}),
            instructions=identity.instructions or instructions,
        )

    def _register_handlers(self) -> None:
        register_proxy_handlers(
            self._server,
            self._session_state,
            refresh_tools=self._runtime.refresh_tools,
            refresh_resources=self._runtime.refresh_resources,
            call_upstream_tool=self._runtime.call_tool,
            read_and_cache_resource=self._runtime.read_and_cache_resource,
            preload_tool_resource=self._runtime.preload_tool_resource,
            to_mcp_tool=to_mcp_tool,
            to_mcp_call_tool_result=to_mcp_call_tool_result,
            to_mcp_resource=to_mcp_resource,
            to_read_resource_contents=to_read_resource_contents,
        )
