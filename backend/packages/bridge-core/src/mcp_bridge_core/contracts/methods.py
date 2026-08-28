"""Behavior contract implemented by a session router and consumed by MCP method adapters.

The contract uses only project-owned protocol values. Routing and downstream SDK adapters depend
on this module independently, preventing transport implementations from becoming application
ports for the bridge engine.
"""

from __future__ import annotations

from typing import Any, Protocol

from .protocol import ReadResourceResult, ResourceDescriptor, ToolCallResult, ToolDescriptor


class McpMethodRouter(Protocol):
    async def list_tools(self) -> list[ToolDescriptor]: ...

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult: ...

    async def preload_tool_resource(self, tool_name: str) -> None: ...

    async def list_resources(self) -> list[ResourceDescriptor]: ...

    async def read_resource(self, uri: str) -> ReadResourceResult: ...
