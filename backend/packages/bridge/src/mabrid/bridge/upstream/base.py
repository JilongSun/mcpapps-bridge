"""Shared MCP SDK session operations and wire-to-core value mapping.

Transport adapters own connection setup; this base owns only operations available after a
``ClientSession`` has been initialized and preservation of supported MCP fields.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from pydantic import AnyUrl

from ..contracts import (
    ReadResourceResult,
    ResourceContent,
    ResourceDescriptor,
    ToolCallResult,
    ToolDescriptor,
    UpstreamIdentity,
)


class BaseSessionUpstreamClient:
    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def list_tools(self) -> list[ToolDescriptor]:
        session = self._require_session()
        result = await session.list_tools()
        return [self._map_tool(tool) for tool in result.tools]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        session = self._require_session()
        result = await session.call_tool(tool_name, arguments=arguments)
        return ToolCallResult(
            content=tuple(self._dump_model_or_value(item) for item in result.content),
            structured_content=self._dump_model_or_none(result.structuredContent),
            is_error=result.isError,
            metadata=self._dump_model_or_none(result.meta) or {},
        )

    async def list_resources(self) -> list[ResourceDescriptor]:
        session = self._require_session()
        result = await session.list_resources()
        return [self._map_resource(resource) for resource in result.resources]

    async def read_resource(self, uri: str) -> ReadResourceResult:
        session = self._require_session()
        result = await session.read_resource(AnyUrl(uri))
        if not result.contents:
            raise ValueError(f"Upstream MCP server returned no contents for resource '{uri}'")
        return ReadResourceResult(
            contents=tuple(self._map_resource_content(content) for content in result.contents),
            metadata=self._dump_model_or_none(getattr(result, "meta", None)) or {},
        )

    async def close(self) -> None:
        stack = self._stack
        self._stack = None
        self._session = None
        if stack is not None:
            await stack.aclose()

    def _require_session(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError("Upstream MCP session is not connected")
        return self._session

    def _map_initialize_result(self, result: Any) -> UpstreamIdentity:
        capabilities = self._dump_model_or_none(result.capabilities) or {}
        server_info = self._dump_model_or_none(result.serverInfo) or {}
        return UpstreamIdentity(
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

    def _map_resource_content(self, content: Any) -> ResourceContent:
        return ResourceContent(
            uri=str(content.uri),
            mime_type=getattr(content, "mimeType", None),
            text=getattr(content, "text", None),
            blob=getattr(content, "blob", None),
            metadata=self._dump_model_or_none(getattr(content, "meta", None)) or {},
        )

    @staticmethod
    def _extract_ui_resource_uri(metadata: dict[str, Any]) -> str | None:
        candidates = [
            metadata.get("openai/outputTemplate"),
            metadata.get("openai/resourceUri"),
            metadata.get("ui"),
            metadata.get("_meta", {}).get("ui")
            if isinstance(metadata.get("_meta"), dict)
            else None,
            metadata.get("openai"),
        ]
        for candidate in candidates:
            if isinstance(candidate, str) and candidate:
                return candidate
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

    @staticmethod
    def _dump_model_or_value(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return value
