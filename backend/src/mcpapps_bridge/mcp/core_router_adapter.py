"""Temporary adapter from monolith router models to bridge-core contracts."""

from __future__ import annotations

from typing import Any

from mcp_bridge_core import AppResource, ResourceDescriptor, ToolCallResult, ToolDescriptor

from .core_mapper import (
    to_core_resource,
    to_core_resource_descriptor,
    to_core_tool,
    to_core_tool_result,
)
from .router import McpSessionRouter


class CoreRouterAdapter:
    def __init__(self, router: McpSessionRouter) -> None:
        self._router = router

    async def list_tools(self) -> list[ToolDescriptor]:
        return [to_core_tool(tool) for tool in await self._router.list_tools()]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        return to_core_tool_result(await self._router.call_tool(tool_name, arguments))

    async def preload_tool_resource(self, tool_name: str) -> None:
        await self._router.preload_tool_resource(tool_name)

    async def list_resources(self) -> list[ResourceDescriptor]:
        return [
            to_core_resource_descriptor(resource)
            for resource in await self._router.list_resources()
        ]

    async def read_resource(self, uri: str) -> AppResource:
        return to_core_resource(await self._router.read_resource(uri))
