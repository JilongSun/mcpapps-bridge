"""MCP Python SDK conversions for bridge-core protocol models."""

from __future__ import annotations

from typing import Any

from mcp import types
from mcp.types import Annotations, ToolAnnotations
from pydantic import AnyUrl

from ..contracts import (
    ReadResourceResult,
    ResourceContent,
    ResourceDescriptor,
    ToolCallResult,
    ToolDescriptor,
)


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
    return types.CallToolResult(
        content=[_to_content_block(item) for item in result.content],
        structuredContent=result.structured_content,
        isError=result.is_error,
        _meta=result.metadata or None,
    )


def _to_content_block(item: dict[str, Any]) -> types.ContentBlock:
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
    if item_type == "resource_link":
        return types.ResourceLink.model_validate(item)
    if item_type == "resource":
        return types.EmbeddedResource.model_validate(item)
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


def to_mcp_read_resource_result(result: ReadResourceResult) -> types.ReadResourceResult:
    return types.ReadResourceResult(
        contents=[to_mcp_resource_content(content) for content in result.contents],
        _meta=result.metadata or None,
    )


def to_mcp_resource_content(
    content: ResourceContent,
) -> types.TextResourceContents | types.BlobResourceContents:
    if content.text is not None:
        return types.TextResourceContents(
            uri=AnyUrl(content.uri),
            mimeType=content.mime_type,
            text=content.text,
            _meta=content.metadata or None,
        )
    if content.blob is None:
        raise ValueError("resource content has no text or blob payload")
    return types.BlobResourceContents(
        uri=AnyUrl(content.uri),
        mimeType=content.mime_type,
        blob=content.blob,
        _meta=content.metadata or None,
    )
