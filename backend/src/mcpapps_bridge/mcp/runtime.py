"""Single-upstream bridge runtime state and behavior."""

from __future__ import annotations

from typing import Any

import anyio

from mcpapps_bridge.models import (
    AppResource,
    ResourceDescriptor,
    ToolCallResult,
    ToolDescriptor,
    UpstreamInitialization,
)
from mcpapps_bridge.session import BridgeSessionState

from .upstream import UpstreamMcpClient, UpstreamServerConfig, build_upstream_client


class BridgeRuntime:
    """Owns upstream lifecycle, state synchronization, and bridge-side caches."""

    def __init__(
        self,
        upstream_config: UpstreamServerConfig,
        session_state: BridgeSessionState,
        *,
        name: str,
        version: str,
        upstream_client: UpstreamMcpClient | None = None,
    ) -> None:
        self._upstream_config = upstream_config
        self._session_state = session_state
        self._name = name
        self._version = version
        self._upstream_client = upstream_client or build_upstream_client(upstream_config)
        self._tool_cache: dict[str, ToolDescriptor] = {}
        self._resource_cache: dict[str, AppResource] = {}
        self._resource_descriptors: dict[str, ResourceDescriptor] = {}
        self._lifecycle_lock = anyio.Lock()
        self._upstream_identity = UpstreamInitialization(server_name=name, server_version=version)
        self._started = False

    @property
    def identity(self) -> UpstreamInitialization:
        return self._upstream_identity

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._started:
                return
            try:
                upstream = await self._upstream_client.connect(self._upstream_config)
            except Exception:
                raise RuntimeError(
                    f"Failed to connect to upstream MCP server "
                    f"(transport={self._upstream_config.transport}). "
                    f"Check that the upstream server is running and the bridge configuration is correct."
                ) from None
            try:
                self._upstream_identity = upstream
                await self._session_state.start(upstream)
                await self.refresh_tools()
                await self.refresh_resources()
            except Exception:
                await self._upstream_client.close()
                raise
            self._started = True

    async def close(self) -> None:
        async with self._lifecycle_lock:
            if not self._started:
                return
            self._started = False
            self._upstream_identity = UpstreamInitialization(
                server_name=self._name,
                server_version=self._version,
            )
            await self._upstream_client.close()

    async def refresh_tools(self) -> list[ToolDescriptor]:
        tools = await self._upstream_client.list_tools()
        self._tool_cache = {tool.name: tool for tool in tools}
        await self._session_state.register_tools(tools)
        return tools

    async def refresh_resources(self) -> list[ResourceDescriptor]:
        try:
            resources = await self._upstream_client.list_resources()
        except Exception:
            resources = self._synthesized_resources_from_tools()
        self._resource_descriptors = {resource.uri: resource for resource in resources}
        return resources

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        return await self._upstream_client.call_tool(tool_name, arguments)

    async def preload_tool_resource(self, tool_name: str) -> None:
        tool = self._tool_cache.get(tool_name)
        if tool is None or tool.ui_resource_uri is None:
            return
        try:
            await self.read_and_cache_resource(tool.ui_resource_uri)
        except Exception as exc:
            await self._session_state.record_error(
                f"Failed to preload UI resource for tool '{tool_name}'",
                details={"resource_uri": tool.ui_resource_uri, "reason": str(exc)},
            )

    async def read_and_cache_resource(self, uri: str) -> AppResource:
        cached = self._resource_cache.get(uri)
        if cached is not None:
            return cached
        resource = await self._upstream_client.read_resource(uri)
        self._resource_cache[uri] = resource
        await self._session_state.load_resource(resource)
        return resource

    def _synthesized_resources_from_tools(self) -> list[ResourceDescriptor]:
        resources: list[ResourceDescriptor] = []
        for tool in self._tool_cache.values():
            if tool.ui_resource_uri is None:
                continue
            resources.append(
                ResourceDescriptor(
                    name=f"{tool.name}_ui",
                    uri=tool.ui_resource_uri,
                    title=tool.title,
                    description=f"UI resource for tool '{tool.name}'",
                    mime_type="text/html;profile=mcp-app",
                )
            )
        return resources
