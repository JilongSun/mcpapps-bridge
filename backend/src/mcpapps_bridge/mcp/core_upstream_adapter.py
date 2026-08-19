"""Temporary adapter from server-owned upstream clients to bridge-core contracts."""

from __future__ import annotations

from typing import Any

from mcp_bridge_core import (
    AppResource,
    ResourceDescriptor,
    ToolCallResult,
    ToolDescriptor,
    UpstreamConfig,
    UpstreamIdentity,
)

from .core_mapper import (
    to_core_identity,
    to_core_resource,
    to_core_resource_descriptor,
    to_core_tool,
    to_core_tool_result,
)
from .upstream import UpstreamMcpClient, UpstreamServerConfig


class CoreUpstreamClientAdapter:
    def __init__(
        self,
        client: UpstreamMcpClient,
        server_config: UpstreamServerConfig,
    ) -> None:
        self._client = client
        self._server_config = server_config

    async def connect(self, config: UpstreamConfig) -> UpstreamIdentity:
        if config.transport != self._server_config.transport:
            raise ValueError("Core and server upstream transports do not match")
        return to_core_identity(await self._client.connect(self._server_config))

    async def list_tools(self) -> list[ToolDescriptor]:
        return [to_core_tool(tool) for tool in await self._client.list_tools()]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        return to_core_tool_result(await self._client.call_tool(tool_name, arguments))

    async def list_resources(self) -> list[ResourceDescriptor]:
        return [
            to_core_resource_descriptor(resource)
            for resource in await self._client.list_resources()
        ]

    async def read_resource(self, uri: str) -> AppResource:
        return to_core_resource(await self._client.read_resource(uri))

    async def close(self) -> None:
        await self._client.close()
