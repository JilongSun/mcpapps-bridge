from __future__ import annotations

from typing import Any

import anyio
import pytest

from mcp_bridge_core import (
    AggregateRouter,
    AppResource,
    BindingAvailabilityChanged,
    BindingAvailabilityStatus,
    BindingPlan,
    BridgeCapabilities,
    BridgeObservation,
    EndpointMode,
    EndpointPlan,
    ResourceDescriptor,
    StdioUpstreamConfig,
    ToolCallResult,
    ToolDescriptor,
    UpstreamConfig,
    UpstreamIdentity,
    UpstreamRuntime,
)

TOOL_UI_URI = "ui://widgets/inspector"
RESULT_UI_URI = "ui://widgets/result"
ORDINARY_RESOURCE_URI = "https://example.test/manual?view=full#install"
LINKED_RESOURCE_URI = "file:///reports/latest.txt"


class RecordingObserver:
    def __init__(self) -> None:
        self.events: list[BridgeObservation] = []

    async def observe(self, event: BridgeObservation) -> None:
        self.events.append(event)


class AggregateFixtureClient:
    def __init__(self) -> None:
        self.tool_calls: list[tuple[str, dict[str, Any]]] = []
        self.resource_reads: list[str] = []
        self.close_count = 0

    async def connect(self, config: UpstreamConfig) -> UpstreamIdentity:
        return UpstreamIdentity(
            server_name="fixture-server",
            server_version="1.0.0",
            protocol_version="2025-11-25",
            supports_tools=True,
            supports_resources=True,
        )

    async def list_tools(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                name="inspect",
                description="Inspect a fixture",
                ui_resource_uri=TOOL_UI_URI,
                metadata={
                    "ui": {"resourceUri": TOOL_UI_URI, "prefersBorder": True},
                    "ui/resourceUri": TOOL_UI_URI,
                    "openai/outputTemplate": TOOL_UI_URI,
                    "openai": {"outputTemplate": TOOL_UI_URI, "visibility": "private"},
                    "_meta": {
                        "ui": {"resourceUri": TOOL_UI_URI, "theme": "system"},
                        "unchanged": True,
                    },
                    "custom": {"resourceUri": TOOL_UI_URI},
                },
            )
        ]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        self.tool_calls.append((tool_name, arguments))
        return ToolCallResult(
            content=(
                {
                    "type": "resource_link",
                    "uri": LINKED_RESOURCE_URI,
                    "name": "latest-report",
                },
                {
                    "type": "resource",
                    "resource": {
                        "uri": RESULT_UI_URI,
                        "mimeType": "text/html;profile=mcp-app",
                        "text": "<p>done</p>",
                    },
                },
                {"type": "text", "text": TOOL_UI_URI},
            ),
            structured_content={"resourceUri": TOOL_UI_URI},
            metadata={"resourceUri": TOOL_UI_URI},
        )

    async def list_resources(self) -> list[ResourceDescriptor]:
        return [
            ResourceDescriptor(
                name="manual",
                uri=ORDINARY_RESOURCE_URI,
                mime_type="text/plain",
            )
        ]

    async def read_resource(self, uri: str) -> AppResource:
        self.resource_reads.append(uri)
        return AppResource(
            uri=uri,
            mime_type=("text/html;profile=mcp-app" if uri.startswith("ui://") else "text/plain"),
            text=f"content for {uri}",
        )

    async def close(self) -> None:
        self.close_count += 1


async def test_aggregate_router_preserves_public_mcp_and_mcp_apps_semantics() -> None:
    client = AggregateFixtureClient()
    observer = RecordingObserver()
    plan = EndpointPlan(
        endpoint_key="endpoint-revision-1",
        display_name="All Tools",
        mode=EndpointMode.AGGREGATE,
        bindings=(
            BindingPlan(
                binding_key="binding-revision-1",
                upstream_key="upstream-revision-1",
                upstream_name="Fixture Server",
                namespace="docs",
                upstream=StdioUpstreamConfig(command="fixture-server"),
            ),
        ),
        capabilities=BridgeCapabilities(tools=True, resources=True),
    )

    def create_runtime(binding: BindingPlan) -> UpstreamRuntime:
        return UpstreamRuntime(
            binding.upstream,
            name=binding.upstream_name,
            version="0.1.0",
            upstream_client=client,
        )

    async with anyio.create_task_group() as workers:
        router = AggregateRouter(
            plan,
            observer,
            "session-1",
            create_runtime,
            workers,
            version="0.1.0",
        )
        await router.start()
        try:
            tools = await router.list_tools()
            assert len(tools) == 1
            tool = tools[0]
            assert tool.name == "docs__inspect"
            assert tool.ui_resource_uri is not None
            assert tool.ui_resource_uri.startswith("ui://docs/")
            assert TOOL_UI_URI not in tool.ui_resource_uri
            assert tool.metadata["ui"] == {
                "resourceUri": tool.ui_resource_uri,
                "prefersBorder": True,
            }
            assert tool.metadata["ui/resourceUri"] == tool.ui_resource_uri
            assert tool.metadata["openai/outputTemplate"] == tool.ui_resource_uri
            assert tool.metadata["openai"] == {
                "outputTemplate": tool.ui_resource_uri,
                "visibility": "private",
            }
            assert tool.metadata["_meta"] == {
                "ui": {"resourceUri": tool.ui_resource_uri, "theme": "system"},
                "unchanged": True,
            }
            assert tool.metadata["custom"] == {"resourceUri": TOOL_UI_URI}

            resources = await router.list_resources()
            assert [resource.name for resource in resources] == ["docs__manual"]
            assert [resource.uri for resource in resources] == [f"docs+{ORDINARY_RESOURCE_URI}"]

            ordinary_resource = await router.read_resource(resources[0].uri)
            assert ordinary_resource.uri == resources[0].uri
            assert client.resource_reads[-1] == ORDINARY_RESOURCE_URI

            tool_resource = await router.read_resource(tool.ui_resource_uri)
            assert tool_resource.uri == tool.ui_resource_uri
            assert client.resource_reads[-1] == TOOL_UI_URI

            result = await router.call_tool("docs__inspect", {"depth": 2})
            assert client.tool_calls == [("inspect", {"depth": 2})]
            assert result.content[0]["uri"] == f"docs+{LINKED_RESOURCE_URI}"
            result_ui_uri = result.content[1]["resource"]["uri"]
            assert result_ui_uri.startswith("ui://docs/")
            assert RESULT_UI_URI not in result_ui_uri
            assert result.content[2]["text"] == TOOL_UI_URI
            assert result.structured_content == {"resourceUri": TOOL_UI_URI}
            assert result.metadata == {"resourceUri": TOOL_UI_URI}

            linked_resource = await router.read_resource(result.content[0]["uri"])
            assert linked_resource.uri == result.content[0]["uri"]
            assert client.resource_reads[-1] == LINKED_RESOURCE_URI

            result_resource = await router.read_resource(result_ui_uri)
            assert result_resource.uri == result_ui_uri
            assert client.resource_reads[-1] == RESULT_UI_URI

            with pytest.raises(KeyError, match="Unknown aggregate resource URI"):
                await router.read_resource("docs+file:///not-registered.txt")
        finally:
            await router.close()

    assert client.close_count == 1
    availability = [
        event for event in observer.events if isinstance(event, BindingAvailabilityChanged)
    ]
    assert [event.status for event in availability] == [
        BindingAvailabilityStatus.UNKNOWN,
        BindingAvailabilityStatus.AVAILABLE,
    ]
