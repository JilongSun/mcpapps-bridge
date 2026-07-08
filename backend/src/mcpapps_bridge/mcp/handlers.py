"""MCP handler registration for the bridge proxy server.

Handler functions are extracted here so they can be extended independently
without modifying the proxy server class.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mcp import types
from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from pydantic import AnyUrl

from mcpapps_bridge.models import AppResource, ResourceDescriptor, ToolCallResult, ToolDescriptor
from mcpapps_bridge.session import BridgeSessionState


def register_proxy_handlers(
    server: Server,
    session_state: BridgeSessionState,
    *,
    refresh_tools: Callable[[], Awaitable[list[ToolDescriptor]]],
    refresh_resources: Callable[[], Awaitable[list[ResourceDescriptor]]],
    call_upstream_tool: Callable[[str, dict[str, Any]], Awaitable[ToolCallResult]],
    read_and_cache_resource: Callable[[str], Awaitable[AppResource]],
    preload_tool_resource: Callable[[str], Awaitable[None]],
    to_mcp_tool: Callable[[ToolDescriptor], types.Tool],
    to_mcp_call_tool_result: Callable[[ToolCallResult], types.CallToolResult],
    to_mcp_resource: Callable[[ResourceDescriptor], types.Resource],
    to_read_resource_contents: Callable[[AppResource], ReadResourceContents],
) -> None:
    """Register tool and resource handlers on the given MCP server.

    All dependencies are injected as callables so that the proxy server
    retains ownership of its internal caches and conversion logic while
    handlers remain independently testable and extensible.
    """

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        tools = await refresh_tools()
        return [to_mcp_tool(tool) for tool in tools]

    @server.call_tool(validate_input=True)
    async def call_tool(tool_name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        started_event = await session_state.start_tool_call(tool_name, arguments)
        result = await call_upstream_tool(tool_name, arguments)
        await session_state.complete_tool_call(
            started_event.call.call_id,
            result,
            failed=result.is_error,
        )
        await preload_tool_resource(tool_name)
        return to_mcp_call_tool_result(result)

    @server.list_resources()
    async def list_resources() -> list[types.Resource]:
        resources = await refresh_resources()
        return [to_mcp_resource(resource) for resource in resources]

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        resource = await read_and_cache_resource(str(uri))
        return [to_read_resource_contents(resource)]
