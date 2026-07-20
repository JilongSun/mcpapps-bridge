"""Session-scoped routing contracts for downstream MCP method handling."""

from __future__ import annotations

from typing import Any, Protocol

from mcpapps_bridge.models import (
    AppResource,
    ResourceDescriptor,
    ToolCallResult,
    ToolDescriptor,
    UpstreamInitialization,
)

from .runtime import UpstreamRuntime


class McpSessionRouter(Protocol):
    @property
    def identity(self) -> UpstreamInitialization: ...

    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def list_tools(self) -> list[ToolDescriptor]: ...

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult: ...

    async def preload_tool_resource(self, tool_name: str) -> None: ...

    async def list_resources(self) -> list[ResourceDescriptor]: ...

    async def read_resource(self, uri: str) -> AppResource: ...


class PassthroughRouter:
    def __init__(self, runtime: UpstreamRuntime) -> None:
        self._runtime = runtime

    @property
    def identity(self) -> UpstreamInitialization:
        return self._runtime.identity

    async def start(self) -> None:
        await self._runtime.start()

    async def close(self) -> None:
        await self._runtime.close()

    async def list_tools(self) -> list[ToolDescriptor]:
        return await self._runtime.refresh_tools()

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolCallResult:
        return await self._runtime.call_tool(tool_name, arguments)

    async def preload_tool_resource(self, tool_name: str) -> None:
        await self._runtime.preload_tool_resource(tool_name)

    async def list_resources(self) -> list[ResourceDescriptor]:
        return await self._runtime.refresh_resources()

    async def read_resource(self, uri: str) -> AppResource:
        return await self._runtime.read_and_cache_resource(uri)
