"""MCP proxy server that mirrors upstream tools and resources."""

from __future__ import annotations

from base64 import b64decode
from typing import Any

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.models import InitializationOptions
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from mcp.types import Annotations, ToolAnnotations
from pydantic import AnyUrl
from starlette.types import Receive, Scope, Send

from mcpapps_bridge.models import AppResource, ResourceDescriptor, ToolCallResult, ToolDescriptor
from mcpapps_bridge.session import BridgeSessionState

from .upstream import StdioServerConfig, StdioUpstreamMcpClient, UpstreamMcpClient


class BridgeProxyServer:
    def __init__(
        self,
        upstream_config: StdioServerConfig,
        session_state: BridgeSessionState,
        *,
        name: str = "mcpapps-proxy",
        version: str = "0.1.0",
        upstream_client: UpstreamMcpClient | None = None,
    ) -> None:
        self._upstream_config = upstream_config
        self._session_state = session_state
        self._name = name
        self._version = version
        self._upstream_client = upstream_client or StdioUpstreamMcpClient()
        self._tool_cache: dict[str, ToolDescriptor] = {}
        self._resource_cache: dict[str, AppResource] = {}
        self._resource_descriptors: dict[str, ResourceDescriptor] = {}
        self._server = Server(name=name, version=version)
        self._sse_transport = SseServerTransport("/mcp/messages/")
        self._lifecycle_lock = anyio.Lock()
        self._started = False
        self._register_handlers()

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._started:
                return
            upstream = await self._upstream_client.connect(self._upstream_config)
            try:
                await self._session_state.start(upstream)
                await self._refresh_tools()
                await self._refresh_resources()
            except Exception:
                await self._upstream_client.close()
                raise
            self._started = True

    async def close(self) -> None:
        async with self._lifecycle_lock:
            if not self._started:
                return
            self._started = False
            await self._upstream_client.close()

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

    async def handle_sse(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.start()
        async with self._sse_transport.connect_sse(scope, receive, send) as streams:
            await self._server.run(
                streams[0],
                streams[1],
                self._create_initialization_options("Protocol-aware MCP Apps SSE proxy."),
            )

    async def handle_sse_post(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._sse_transport.handle_post_message(scope, receive, send)

    def _create_initialization_options(self, instructions: str) -> InitializationOptions:
        return InitializationOptions(
            server_name=self._name,
            server_version=self._version,
            capabilities=self._server.get_capabilities(NotificationOptions(), {}),
            instructions=instructions,
        )

    def _register_handlers(self) -> None:
        @self._server.list_tools()
        async def list_tools() -> list[types.Tool]:
            tools = await self._refresh_tools()
            return [self._to_mcp_tool(tool) for tool in tools]

        @self._server.call_tool(validate_input=True)
        async def call_tool(tool_name: str, arguments: dict[str, Any]) -> types.CallToolResult:
            started_event = await self._session_state.start_tool_call(tool_name, arguments)
            result = await self._upstream_client.call_tool(tool_name, arguments)
            await self._session_state.complete_tool_call(
                started_event.call.call_id,
                result,
                failed=result.is_error,
            )

            await self._preload_tool_resource(tool_name)
            return self._to_mcp_call_tool_result(result)

        @self._server.list_resources()
        async def list_resources() -> list[types.Resource]:
            resources = await self._refresh_resources()
            return [self._to_mcp_resource(resource) for resource in resources]

        @self._server.read_resource()
        async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
            resource = await self._read_and_cache_resource(str(uri))
            return [self._to_read_resource_contents(resource)]

    async def _refresh_tools(self) -> list[ToolDescriptor]:
        tools = await self._upstream_client.list_tools()
        self._tool_cache = {tool.name: tool for tool in tools}
        await self._session_state.register_tools(tools)
        return tools

    async def _refresh_resources(self) -> list[ResourceDescriptor]:
        try:
            resources = await self._upstream_client.list_resources()
        except Exception:
            resources = self._synthesized_resources_from_tools()
        self._resource_descriptors = {resource.uri: resource for resource in resources}
        return resources

    async def _preload_tool_resource(self, tool_name: str) -> None:
        tool = self._tool_cache.get(tool_name)
        if tool is None or tool.ui_resource_uri is None:
            return
        try:
            await self._read_and_cache_resource(tool.ui_resource_uri)
        except Exception as exc:
            await self._session_state.record_error(
                f"Failed to preload UI resource for tool '{tool_name}'",
                details={"resource_uri": tool.ui_resource_uri, "reason": str(exc)},
            )

    async def _read_and_cache_resource(self, uri: str) -> AppResource:
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

    def _to_mcp_tool(self, tool: ToolDescriptor) -> types.Tool:
        meta = dict(tool.metadata)
        if tool.ui_resource_uri and "ui" not in meta:
            meta["ui"] = {"resourceUri": tool.ui_resource_uri}
        return types.Tool(
            name=tool.name,
            title=tool.title,
            description=tool.description,
            inputSchema=tool.input_schema,
            outputSchema=tool.output_schema,
            annotations=ToolAnnotations(**tool.annotations) if tool.annotations else None,
            _meta=meta or None,
        )

    def _to_mcp_call_tool_result(self, result: ToolCallResult) -> types.CallToolResult:
        content = [self._to_content_block(item) for item in result.content]
        return types.CallToolResult(
            content=content,
            structuredContent=result.structured_content,
            isError=result.is_error,
            _meta=result.metadata or None,
        )

    def _to_content_block(self, item: dict[str, Any]) -> types.ContentBlock:
        item_type = item.get("type")
        if item_type == "text":
            return types.TextContent(type="text", text=str(item.get("text", "")))
        if item_type == "image":
            return types.ImageContent(
                type="image",
                data=str(item.get("data", "")),
                mimeType=str(item.get("mimeType", "image/png")),
            )
        if item_type == "audio":
            return types.AudioContent(
                type="audio",
                data=str(item.get("data", "")),
                mimeType=str(item.get("mimeType", "audio/wav")),
            )
        if item_type == "resource":
            resource = item.get("resource", {})
            return types.EmbeddedResource(
                type="resource",
                resource=types.TextResourceContents(
                    uri=resource.get("uri", "embedded://resource"),
                    mimeType=resource.get("mimeType", "text/plain"),
                    text=resource.get("text", ""),
                    _meta=resource.get("meta"),
                ),
            )
        return types.TextContent(type="text", text=str(item))

    def _to_mcp_resource(self, resource: ResourceDescriptor) -> types.Resource:
        return types.Resource(
            name=resource.name,
            title=resource.title,
            uri=AnyUrl(resource.uri),
            description=resource.description,
            mimeType=resource.mime_type,
            annotations=Annotations(**resource.annotations) if resource.annotations else None,
            size=resource.size,
            _meta=resource.metadata or None,
        )

    def _to_read_resource_contents(self, resource: AppResource) -> ReadResourceContents:
        if resource.text is not None:
            return ReadResourceContents(
                content=resource.text,
                mime_type=resource.mime_type,
                meta=resource.metadata or None,
            )
        if resource.blob is not None:
            return ReadResourceContents(
                content=b64decode(resource.blob),
                mime_type=resource.mime_type,
                meta=resource.metadata or None,
            )
        return ReadResourceContents(
            content="", mime_type=resource.mime_type, meta=resource.metadata or None
        )


def build_proxy_server(
    upstream_config: StdioServerConfig,
    session_state: BridgeSessionState,
    *,
    name: str = "mcpapps-proxy",
    version: str = "0.1.0",
    upstream_client: UpstreamMcpClient | None = None,
) -> BridgeProxyServer:
    return BridgeProxyServer(
        upstream_config,
        session_state,
        name=name,
        version=version,
        upstream_client=upstream_client,
    )
