from __future__ import annotations

from typing import Any

import anyio

from mabrid.bridge import (
    BridgeErrorRaised,
    BridgeObservation,
    ReadResourceResult,
    ResourceDescriptor,
    StdioUpstreamConfig,
    ToolCallResult,
    ToolDescriptor,
    UpstreamConfig,
    UpstreamIdentity,
)
from mabrid.bridge.routing import PassthroughRouter
from mabrid.bridge.upstream import UpstreamRuntime


class RecordingObserver:
    def __init__(self) -> None:
        self.events: list[BridgeObservation] = []

    async def observe(self, event: BridgeObservation) -> None:
        self.events.append(event)


class FailingApplicationResourceClient:
    async def connect(self, config: UpstreamConfig) -> UpstreamIdentity:
        return UpstreamIdentity(server_name="fixture", supports_tools=True)

    async def list_tools(self) -> list[ToolDescriptor]:
        return [ToolDescriptor(name="inspect", ui_resource_uri="ui://fixture/inspect")]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        return ToolCallResult(content=({"type": "text", "text": "completed"},))

    async def list_resources(self) -> list[ResourceDescriptor]:
        raise AssertionError("resources/list must not be called without advertised capability")

    async def read_resource(self, uri: str) -> ReadResourceResult:
        raise RuntimeError("resource unavailable")

    async def close(self) -> None:
        return None


async def test_application_resource_failure_does_not_replace_the_tool_result() -> None:
    observer = RecordingObserver()
    runtime = UpstreamRuntime(
        StdioUpstreamConfig(command="fixture-server"),
        name="fixture",
        version="0.1.0",
        upstream_client=FailingApplicationResourceClient(),
    )

    async with anyio.create_task_group() as workers:
        router = PassthroughRouter(runtime, observer, "session-1", workers)
        await router.start()
        try:
            result = await router.call_tool("inspect", {})
            await router.load_tool_resource("inspect", "operation-1")
        finally:
            await router.close()

    assert result.content == ({"type": "text", "text": "completed"},)
    error = next(event for event in observer.events if isinstance(event, BridgeErrorRaised))
    assert error.operation == "application_resource_load"
    assert error.operation_key == "operation-1"
    assert error.failure.message == "Failed to load UI resource for tool 'inspect'"
