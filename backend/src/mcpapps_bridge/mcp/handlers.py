"""MCP method handlers for one upstream-backed downstream server."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from mcp import types
from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp_bridge_core import (
    BridgeFailure,
    BridgeFailureCode,
    BridgeObserver,
    ToolCallCompleted,
    ToolCallStarted,
)
from pydantic import AnyUrl

from .core_mapper import to_core_tool_result
from .mapper import (
    to_mcp_call_tool_result,
    to_mcp_resource,
    to_mcp_tool,
    to_read_resource_contents,
)
from .router import McpSessionRouter


class ProxyHandlers:
    """Implements MCP methods for one downstream server."""

    def __init__(
        self,
        router: McpSessionRouter,
        observer: BridgeObserver,
        session_key: str,
    ) -> None:
        self._router = router
        self._observer = observer
        self._session_key = session_key

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
        tools = await self._router.list_tools()
        return [to_mcp_tool(tool) for tool in tools]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        operation_key = str(uuid4())
        await self._observer.observe(
            ToolCallStarted(
                session_key=self._session_key,
                operation_key=operation_key,
                tool_name=tool_name,
                arguments=arguments,
            )
        )
        try:
            result = await self._router.call_tool(tool_name, arguments)
        except Exception as exc:
            await self._observer.observe(
                ToolCallCompleted(
                    session_key=self._session_key,
                    operation_key=operation_key,
                    failure=BridgeFailure(
                        code=BridgeFailureCode.UPSTREAM_PROTOCOL,
                        message=str(exc),
                        retryable=True,
                        details={"exception_type": type(exc).__name__},
                    ),
                ),
            )
            raise
        await self._observer.observe(
            ToolCallCompleted(
                session_key=self._session_key,
                operation_key=operation_key,
                result=to_core_tool_result(result),
            )
        )
        await self._router.preload_tool_resource(tool_name)
        return to_mcp_call_tool_result(result)

    async def list_resources(self) -> list[types.Resource]:
        resources = await self._router.list_resources()
        return [to_mcp_resource(resource) for resource in resources]

    async def read_resource(self, uri: str) -> list[ReadResourceContents]:
        resource = await self._router.read_resource(uri)
        return [to_read_resource_contents(resource)]
