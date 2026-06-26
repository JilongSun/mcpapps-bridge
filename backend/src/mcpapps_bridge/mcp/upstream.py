"""Abstract and concrete upstream MCP client implementations."""

from __future__ import annotations

from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Protocol

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import AnyUrl
from pydantic import BaseModel, Field

from mcpapps_bridge.models import (
    AppResource,
    ResourceDescriptor,
    ToolCallResult,
    ToolDescriptor,
    UpstreamInitialization,
)


class StdioServerConfig(BaseModel):
    command: str
    args: list[str] = Field(default_factory=list)
    cwd: Path | None = None
    env: dict[str, str] = Field(default_factory=dict)


class UpstreamMcpClient(Protocol):
    async def connect(self, config: StdioServerConfig) -> UpstreamInitialization: ...

    async def list_tools(self) -> list[ToolDescriptor]: ...

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult: ...

    async def list_resources(self) -> list[ResourceDescriptor]: ...

    async def read_resource(self, uri: str) -> AppResource: ...

    async def close(self) -> None: ...


class StdioUpstreamMcpClient:
    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._config: StdioServerConfig | None = None

    async def connect(self, config: StdioServerConfig) -> UpstreamInitialization:
        if self._session is not None:
            await self.close()

        stack = AsyncExitStack()
        try:
            server = StdioServerParameters(
                command=config.command,
                args=config.args,
                cwd=str(config.cwd) if config.cwd is not None else None,
                env=config.env or None,
            )
            read_stream, write_stream = await stack.enter_async_context(stdio_client(server))
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            result = await session.initialize()
        except Exception:
            await stack.aclose()
            raise

        self._stack = stack
        self._session = session
        self._config = config
        return self._map_initialize_result(result)

    async def list_tools(self) -> list[ToolDescriptor]:
        session = self._require_session()
        result = await session.list_tools()
        return [self._map_tool(tool) for tool in result.tools]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        session = self._require_session()
        result = await session.call_tool(tool_name, arguments=arguments)
        return ToolCallResult(
            content=[self._dump_model_or_value(item) for item in result.content],
            structured_content=self._dump_model_or_none(result.structuredContent),
            is_error=result.isError,
            metadata=self._dump_model_or_none(result.meta) or {},
        )

    async def list_resources(self) -> list[ResourceDescriptor]:
        session = self._require_session()
        result = await session.list_resources()
        return [self._map_resource(resource) for resource in result.resources]

    async def read_resource(self, uri: str) -> AppResource:
        session = self._require_session()
        parsed_uri = AnyUrl(uri)
        result = await session.read_resource(parsed_uri)
        if not result.contents:
            raise ValueError(f"Upstream MCP server returned no contents for resource '{uri}'")

        primary = result.contents[0]
        metadata = self._dump_model_or_none(getattr(primary, "meta", None)) or {}
        if len(result.contents) > 1:
            metadata = {**metadata, "additional_contents": len(result.contents) - 1}

        return AppResource(
            uri=str(primary.uri),
            mime_type=getattr(primary, "mimeType", "application/octet-stream"),
            text=getattr(primary, "text", None),
            blob=getattr(primary, "blob", None),
            metadata=metadata,
        )

    async def close(self) -> None:
        stack = self._stack
        self._stack = None
        self._session = None
        self._config = None
        if stack is not None:
            await stack.aclose()

    def _require_session(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError("Upstream MCP session is not connected")
        return self._session

    def _map_initialize_result(self, result: Any) -> UpstreamInitialization:
        capabilities = self._dump_model_or_none(result.capabilities) or {}
        server_info = self._dump_model_or_none(result.serverInfo) or {}
        return UpstreamInitialization(
            server_name=server_info.get("name", "unknown-server"),
            server_version=server_info.get("version"),
            protocol_version=result.protocolVersion,
            instructions=result.instructions,
            supports_tools="tools" in capabilities,
            supports_resources="resources" in capabilities,
            raw_capabilities=capabilities,
        )

    def _map_tool(self, tool: Any) -> ToolDescriptor:
        metadata = self._dump_model_or_none(getattr(tool, "meta", None)) or {}
        annotations = self._dump_model_or_none(getattr(tool, "annotations", None)) or {}
        return ToolDescriptor(
            name=tool.name,
            title=getattr(tool, "title", None),
            description=getattr(tool, "description", None),
            input_schema=self._dump_model_or_none(getattr(tool, "inputSchema", None)) or {},
            output_schema=self._dump_model_or_none(getattr(tool, "outputSchema", None)),
            annotations=annotations,
            ui_resource_uri=self._extract_ui_resource_uri(metadata),
            metadata=metadata,
        )

    def _map_resource(self, resource: Any) -> ResourceDescriptor:
        metadata = self._dump_model_or_none(getattr(resource, "meta", None)) or {}
        annotations = self._dump_model_or_none(getattr(resource, "annotations", None)) or {}
        return ResourceDescriptor(
            name=resource.name,
            uri=str(resource.uri),
            title=getattr(resource, "title", None),
            description=getattr(resource, "description", None),
            mime_type=getattr(resource, "mimeType", None),
            annotations=annotations,
            metadata=metadata,
            size=getattr(resource, "size", None),
        )

    def _extract_ui_resource_uri(self, metadata: dict[str, Any]) -> str | None:
        candidates = [
            metadata.get("ui"),
            metadata.get("_meta", {}).get("ui")
            if isinstance(metadata.get("_meta"), dict)
            else None,
            metadata.get("openai"),
        ]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            resource_uri = candidate.get("resourceUri") or candidate.get("outputTemplate")
            if isinstance(resource_uri, str) and resource_uri:
                return resource_uri
        return None

    def _dump_model_or_none(self, value: Any) -> Any:
        if value is None:
            return None
        return self._dump_model_or_value(value)

    def _dump_model_or_value(self, value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return value
