from __future__ import annotations

from typing import Any

import anyio

from mcpapps_bridge.mcp.runtime import UpstreamRuntime
from mcpapps_bridge.mcp.upstream import UpstreamServerConfig
from mcpapps_bridge.models import (
    AppResource,
    ResourceDescriptor,
    ToolCallResult,
    ToolDescriptor,
    UpstreamInitialization,
)


class TaskRecordingUpstreamClient:
    def __init__(self) -> None:
        self.operations: list[tuple[str, int]] = []

    async def connect(self, config: UpstreamServerConfig) -> UpstreamInitialization:
        self._record("connect")
        return UpstreamInitialization(server_name="test-upstream")

    async def list_tools(self) -> list[ToolDescriptor]:
        self._record("tools/list")
        return [ToolDescriptor(name="echo")]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        self._record("tools/call")
        return ToolCallResult(content=[{"type": "text", "text": tool_name}])

    async def list_resources(self) -> list[ResourceDescriptor]:
        self._record("resources/list")
        return [ResourceDescriptor(name="status", uri="data://status")]

    async def read_resource(self, uri: str) -> AppResource:
        self._record("resources/read")
        return AppResource(uri=uri, mime_type="text/plain", text="ready")

    async def close(self) -> None:
        self._record("close")

    def _record(self, operation: str) -> None:
        self.operations.append((operation, anyio.get_current_task().id))


async def test_upstream_client_lifecycle_stays_in_one_owner_task() -> None:
    client = TaskRecordingUpstreamClient()
    runtime = UpstreamRuntime(
        UpstreamServerConfig(),
        name="test-upstream",
        version="0.1.0",
        upstream_client=client,
    )

    async with anyio.create_task_group() as workers:
        await runtime.start_worker(workers)

        async def discover() -> None:
            await runtime.start()
            assert [tool.name for tool in await runtime.refresh_tools()] == ["echo"]

        async with anyio.create_task_group() as callers:
            callers.start_soon(discover)

        assert [resource.uri for resource in await runtime.refresh_resources()] == ["data://status"]
        assert (await runtime.call_tool("echo", {})).is_error is False
        assert (await runtime.read_and_cache_resource("data://status")).text == "ready"
        await runtime.close()

        async def reconnect() -> None:
            await runtime.start()

        async with anyio.create_task_group() as callers:
            callers.start_soon(reconnect)

        await runtime.shutdown_worker()

    operation_names = [operation for operation, _ in client.operations]
    assert operation_names == [
        "connect",
        "tools/list",
        "resources/list",
        "tools/call",
        "resources/read",
        "close",
        "connect",
        "close",
    ]
    assert len({task_id for _, task_id in client.operations}) == 1
