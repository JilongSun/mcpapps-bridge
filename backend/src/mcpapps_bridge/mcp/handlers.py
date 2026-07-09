"""MCP method handlers for one upstream-backed downstream server."""

from __future__ import annotations

from typing import Any

from mcp import types
from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from pydantic import AnyUrl

from mcpapps_bridge.session import BridgeSessionStore

from .mapper import (
    to_mcp_call_tool_result,
    to_mcp_resource,
    to_mcp_tool,
    to_read_resource_contents,
)
from .runtime import UpstreamRuntime


class ProxyHandlers:
    """Implements MCP methods for one downstream server."""

    def __init__(self, runtime: UpstreamRuntime, session_store: BridgeSessionStore) -> None:
        self._runtime = runtime
        self._session_store = session_store

    def register(self, server: Server) -> None:
        @server.list_tools()
        async def list_tools() -> list[types.Tool]:
            return await self.list_tools()

        @server.call_tool(validate_input=True)
        async def call_tool(tool_name: str, arguments: dict[str, Any]) -> types.CallToolResult:
            return await self.call_tool(tool_name, arguments)

        @server.list_resources()
        async def list_resources() -> list[types.Resource]:
            return await self.list_resources()

        @server.read_resource()
        async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
            return await self.read_resource(str(uri))

    async def list_tools(self) -> list[types.Tool]:
        tools = await self._runtime.refresh_tools()
        return [to_mcp_tool(tool) for tool in tools]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        started_event = await self._session_store.start_tool_call(tool_name, arguments)
        result = await self._runtime.call_tool(tool_name, arguments)
        await self._session_store.complete_tool_call(
            started_event.call.call_id,
            result,
            failed=result.is_error,
        )
        await self._runtime.preload_tool_resource(tool_name)
        return to_mcp_call_tool_result(result)

    async def list_resources(self) -> list[types.Resource]:
        resources = await self._runtime.refresh_resources()
        return [to_mcp_resource(resource) for resource in resources]

    async def read_resource(self, uri: str) -> list[ReadResourceContents]:
        resource = await self._runtime.read_and_cache_resource(uri)
        return [to_read_resource_contents(resource)]
