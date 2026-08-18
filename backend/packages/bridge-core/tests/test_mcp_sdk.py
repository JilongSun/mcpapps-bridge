from __future__ import annotations

from base64 import b64encode

from mcp_bridge_core import AppResource, ResourceDescriptor, ToolCallResult, ToolDescriptor
from mcp_bridge_core._mcp_sdk import (
    to_mcp_call_tool_result,
    to_mcp_resource,
    to_mcp_tool,
    to_read_resource_contents,
)


def test_tool_mapping_preserves_mcp_apps_metadata() -> None:
    tool = ToolDescriptor(
        name="inspect",
        input_schema={"type": "object"},
        ui_resource_uri="ui://opaque/widget",
        metadata={"custom": {"enabled": True}},
    )

    mapped = to_mcp_tool(tool).model_dump(by_alias=True, exclude_none=True)

    assert mapped["inputSchema"] == {"type": "object"}
    assert mapped["_meta"] == {
        "custom": {"enabled": True},
        "ui": {"resourceUri": "ui://opaque/widget"},
    }


def test_tool_result_mapping_preserves_protocol_fields() -> None:
    result = ToolCallResult(
        content=({"type": "text", "text": "ready"},),
        structured_content={"status": "ready"},
        metadata={"resourceUri": "ui://opaque/result"},
    )

    mapped = to_mcp_call_tool_result(result).model_dump(by_alias=True, exclude_none=True)

    assert mapped["content"] == [{"type": "text", "text": "ready"}]
    assert mapped["structuredContent"] == {"status": "ready"}
    assert mapped["isError"] is False
    assert mapped["_meta"] == {"resourceUri": "ui://opaque/result"}


def test_resource_mapping_preserves_descriptor_and_decodes_blob() -> None:
    descriptor = ResourceDescriptor(
        name="report",
        uri="file:///reports/latest.txt",
        mime_type="text/plain",
        metadata={"audience": "agent"},
    )
    resource = AppResource(
        uri=descriptor.uri,
        mime_type="application/octet-stream",
        blob=b64encode(b"report").decode("ascii"),
        metadata={"checksum": "fixture"},
    )

    mapped_descriptor = to_mcp_resource(descriptor).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    mapped_contents = to_read_resource_contents(resource)

    assert mapped_descriptor["uri"] == descriptor.uri
    assert mapped_descriptor["mimeType"] == "text/plain"
    assert mapped_descriptor["_meta"] == {"audience": "agent"}
    assert mapped_contents.content == b"report"
    assert mapped_contents.mime_type == "application/octet-stream"
    assert mapped_contents.meta == {"checksum": "fixture"}
