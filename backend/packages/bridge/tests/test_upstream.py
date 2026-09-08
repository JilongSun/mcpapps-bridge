from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast

import mabrid.bridge.upstream.streamable_http as upstream_module
import pytest
from mcp import ClientSession, types
from pydantic import AnyHttpUrl, AnyUrl

from mabrid.bridge import (
    SseUpstreamConfig,
    StdioUpstreamConfig,
    StreamableHttpUpstreamConfig,
)
from mabrid.bridge.upstream.base import BaseSessionUpstreamClient
from mabrid.bridge.upstream import (
    SseUpstreamClient,
    StdioUpstreamClient,
    StreamableHttpUpstreamClient,
    build_upstream_client,
)


class FakeHttpClient:
    async def __aenter__(self) -> FakeHttpClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeClientSession:
    def __init__(self, read_stream: object, write_stream: object) -> None:
        self.read_stream = read_stream
        self.write_stream = write_stream

    async def __aenter__(self) -> FakeClientSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def initialize(self) -> Any:
        return SimpleNamespace(
            capabilities={},
            serverInfo={"name": "fixture", "version": "1.0.0"},
            protocolVersion="2025-11-25",
            instructions=None,
        )


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
            meta={"requestId": "fixture-read"},
            contents=[
                SimpleNamespace(
                    uri=uri,
                    mimeType="text/plain",
                    text="fixture",
                    blob=None,
                    meta={"checksum": "test"},
                ),
                SimpleNamespace(
                    uri=AnyUrl("file:///fixture/related.txt"),
                    mimeType="text/plain",
                    text="additional",
                    meta={"related": True},
                ),
            ],
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
    assert resource.metadata == {"requestId": "fixture-read"}
    assert [content.uri for content in resource.contents] == [
        "file:///fixture/manual.txt",
        "file:///fixture/related.txt",
    ]
    assert [content.text for content in resource.contents] == ["fixture", "additional"]
    assert resource.contents[0].metadata == {"checksum": "test"}
    assert resource.contents[1].metadata == {"related": True}


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


async def test_streamable_http_uses_the_configured_url_without_probing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_urls: list[str] = []
    http_client = FakeHttpClient()

    @asynccontextmanager
    async def fake_streamable_http_client(
        url: str,
        *,
        http_client: object,
    ) -> AsyncIterator[tuple[object, object, None]]:
        requested_urls.append(url)
        yield object(), object(), None

    monkeypatch.setattr(upstream_module.httpx, "AsyncClient", lambda **_: http_client)
    monkeypatch.setattr(upstream_module, "streamable_http_client", fake_streamable_http_client)
    monkeypatch.setattr(upstream_module, "ClientSession", FakeClientSession)

    client = StreamableHttpUpstreamClient()
    identity = await client.connect(
        StreamableHttpUpstreamConfig(
            url=AnyHttpUrl("http://localhost:8760/mcp"),
            timeout_seconds=5,
        )
    )
    await client.close()

    assert requested_urls == ["http://localhost:8760/mcp"]
    assert identity.server_name == "fixture"
