"""Downstream MCP server and transport hosting."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.types import Receive, Scope, Send

from mcpapps_bridge.models import UpstreamInitialization

from .handlers import ProxyHandlers


class BridgeDownstreamServer:
    """Hosts the downstream MCP protocol surface for one bridge runtime."""

    def __init__(
        self,
        handlers: ProxyHandlers,
        identity_provider: Callable[[], UpstreamInitialization],
        *,
        name: str,
        version: str,
    ) -> None:
        self._handlers = handlers
        self._identity_provider = identity_provider
        self._version = version
        self._server = Server(name=name, version=version)
        self._sse_transport = SseServerTransport("/messages")
        self._streamable_http = StreamableHTTPSessionManager(app=self._server)
        self._handlers.register(self._server)

    async def serve_stdio(self) -> None:
        async with stdio_server() as (read_stream, write_stream):
            await self._server.run(
                read_stream,
                write_stream,
                self._create_initialization_options("Protocol-aware MCP Apps stdio proxy."),
            )

    @asynccontextmanager
    async def run_http_transports(self) -> AsyncIterator[None]:
        async with self._streamable_http.run():
            yield

    async def handle_streamable_http(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._streamable_http.handle_request(scope, receive, send)

    async def handle_sse(self, scope: Scope, receive: Receive, send: Send) -> None:
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
        identity = self._identity_provider()
        return InitializationOptions(
            server_name=identity.server_name,
            server_version=identity.server_version or self._version,
            capabilities=self._server.get_capabilities(NotificationOptions(), {}),
            instructions=identity.instructions or instructions,
        )
