"""MCP protocol type mapping helpers."""

from __future__ import annotations

from base64 import b64decode
from typing import Any

from mcp import types
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.types import Annotations, ToolAnnotations
from pydantic import AnyUrl

from mcpapps_bridge.models import AppResource, ResourceDescriptor, ToolCallResult, ToolDescriptor


def to_mcp_tool(tool: ToolDescriptor) -> types.Tool:
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


def to_mcp_call_tool_result(result: ToolCallResult) -> types.CallToolResult:
    content = [to_content_block(item) for item in result.content]
    return types.CallToolResult(
        content=content,
        structuredContent=result.structured_content,
        isError=result.is_error,
        _meta=result.metadata or None,
    )


def to_content_block(item: dict[str, Any]) -> types.ContentBlock:
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


def to_mcp_resource(resource: ResourceDescriptor) -> types.Resource:
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


def to_read_resource_contents(resource: AppResource) -> ReadResourceContents:
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
