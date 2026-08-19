from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from mcp import ClientSession, types
from pydantic import AnyHttpUrl, AnyUrl

from mcp_bridge_core import (
    SseUpstreamClient,
    SseUpstreamConfig,
    StdioUpstreamClient,
    StdioUpstreamConfig,
    StreamableHttpUpstreamClient,
    StreamableHttpUpstreamConfig,
    build_upstream_client,
)
from mcp_bridge_core.upstream import BaseSessionUpstreamClient


class FixtureSession:
    async def list_tools(self) -> Any:
        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name="inspect",
                    title="Inspector",
                    description="Inspect a fixture",
                    inputSchema={"type": "object"},
                    outputSchema=None,
                    annotations=None,
                    meta={
                        "ui": {"resourceUri": "ui://fixture/inspector"},
                        "custom": True,
                    },
                )
            ]
        )

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        return SimpleNamespace(
            content=[types.TextContent(type="text", text=tool_name)],
            structuredContent={"arguments": arguments},
            isError=False,
            meta={"requestId": "fixture-request"},
        )

    async def list_resources(self) -> Any:
        return SimpleNamespace(
            resources=[
                SimpleNamespace(
                    name="manual",
                    uri=AnyUrl("file:///fixture/manual.txt"),
                    title=None,
                    description=None,
                    mimeType="text/plain",
                    annotations=None,
                    size=7,
                    meta={"audience": "agent"},
                )
            ]
        )

    async def read_resource(self, uri: AnyUrl) -> Any:
        return SimpleNamespace(
            contents=[
                SimpleNamespace(
                    uri=uri,
                    mimeType="text/plain",
                    text="fixture",
                    blob=None,
                    meta={"checksum": "test"},
                ),
                SimpleNamespace(uri=uri, mimeType="text/plain", text="additional"),
            ]
        )


async def test_upstream_sdk_mapping_preserves_core_protocol_fields() -> None:
    client = BaseSessionUpstreamClient()
    client._session = cast(ClientSession, FixtureSession())

    identity = client._map_initialize_result(
        SimpleNamespace(
            capabilities={"tools": {}, "resources": {}},
            serverInfo={"name": "fixture", "version": "1.0.0"},
            protocolVersion="2025-11-25",
            instructions="Use fixture tools.",
        )
    )
    tools = await client.list_tools()
    result = await client.call_tool("inspect", {"depth": 2})
    resources = await client.list_resources()
    resource = await client.read_resource("file:///fixture/manual.txt")

    assert identity.server_name == "fixture"
    assert identity.supports_tools is True
    assert identity.supports_resources is True
    assert tools[0].ui_resource_uri == "ui://fixture/inspector"
    assert tools[0].metadata["custom"] is True
    assert result.content[0]["type"] == "text"
    assert result.content[0]["text"] == "inspect"
    assert result.structured_content == {"arguments": {"depth": 2}}
    assert result.metadata == {"requestId": "fixture-request"}
    assert resources[0].uri == "file:///fixture/manual.txt"
    assert resources[0].metadata == {"audience": "agent"}
    assert resource.text == "fixture"
    assert resource.metadata == {"checksum": "test", "additional_contents": 1}


def test_upstream_factory_selects_transport_connector() -> None:
    assert isinstance(
        build_upstream_client(StdioUpstreamConfig(command="fixture-server")),
        StdioUpstreamClient,
    )
    assert isinstance(
        build_upstream_client(SseUpstreamConfig(url=AnyHttpUrl("https://example.test/sse"))),
        SseUpstreamClient,
    )
    assert isinstance(
        build_upstream_client(
            StreamableHttpUpstreamConfig(url=AnyHttpUrl("https://example.test/mcp"))
        ),
        StreamableHttpUpstreamClient,
    )
