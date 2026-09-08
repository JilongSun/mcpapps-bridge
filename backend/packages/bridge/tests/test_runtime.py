from __future__ import annotations

from typing import Any

import anyio
import pytest

from mabrid.bridge import (
    ReadResourceResult,
    ResourceContent,
    ResourceDescriptor,
    StdioUpstreamConfig,
    ToolCallResult,
    ToolDescriptor,
    UpstreamConfig,
    UpstreamIdentity,
)
from mabrid.bridge.upstream import UpstreamRuntime


class TaskRecordingUpstreamClient:
    def __init__(self) -> None:
        self.operations: list[tuple[str, int]] = []

    async def connect(self, config: UpstreamConfig) -> UpstreamIdentity:
        self._record("connect")
        return UpstreamIdentity(server_name="test-upstream", supports_resources=True)

    async def list_tools(self) -> list[ToolDescriptor]:
        self._record("tools/list")
        return [ToolDescriptor(name="echo")]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        self._record("tools/call")
        return ToolCallResult(content=({"type": "text", "text": tool_name},))

    async def list_resources(self) -> list[ResourceDescriptor]:
        self._record("resources/list")
        return [ResourceDescriptor(name="status", uri="data://status")]

    async def read_resource(self, uri: str) -> ReadResourceResult:
        self._record("resources/read")
        return ReadResourceResult(
            contents=(ResourceContent(uri=uri, mime_type="text/plain", text="ready"),)
        )

    async def close(self) -> None:
        self._record("close")

    def _record(self, operation: str) -> None:
        self.operations.append((operation, anyio.get_current_task().id))


async def test_upstream_client_lifecycle_stays_in_one_owner_task() -> None:
    client = TaskRecordingUpstreamClient()
    runtime = UpstreamRuntime(
        StdioUpstreamConfig(command="fixture-server"),
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
        resource = await runtime.read_and_cache_resource("data://status")
        assert resource.contents[0].text == "ready"
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


class ToolOnlyUpstreamClient(TaskRecordingUpstreamClient):
    async def connect(self, config: UpstreamConfig) -> UpstreamIdentity:
        self._record("connect")
        return UpstreamIdentity(server_name="tool-only", supports_tools=True)

    async def list_tools(self) -> list[ToolDescriptor]:
        self._record("tools/list")
        return [ToolDescriptor(name="inspect", ui_resource_uri="ui://fixture/inspect")]

    async def list_resources(self) -> list[ResourceDescriptor]:
        raise AssertionError("resources/list must not be called without advertised capability")


class FailingResourceUpstreamClient(TaskRecordingUpstreamClient):
    async def list_resources(self) -> list[ResourceDescriptor]:
        self._record("resources/list")
        raise RuntimeError("resource discovery failed")


async def test_runtime_synthesizes_tool_ui_only_without_resources_capability() -> None:
    client = ToolOnlyUpstreamClient()
    runtime = UpstreamRuntime(
        StdioUpstreamConfig(command="fixture-server"),
        name="tool-only",
        version="0.1.0",
        upstream_client=client,
    )

    async with anyio.create_task_group() as workers:
        await runtime.start_worker(workers)
        await runtime.start()
        await runtime.refresh_tools()
        resources = await runtime.refresh_resources()
        await runtime.shutdown_worker()

    assert [resource.uri for resource in resources] == ["ui://fixture/inspect"]
    assert [operation for operation, _ in client.operations] == ["connect", "tools/list", "close"]


async def test_runtime_propagates_advertised_resource_discovery_failure() -> None:
    client = FailingResourceUpstreamClient()
    runtime = UpstreamRuntime(
        StdioUpstreamConfig(command="fixture-server"),
        name="resource-server",
        version="0.1.0",
        upstream_client=client,
    )

    async with anyio.create_task_group() as workers:
        await runtime.start_worker(workers)
        await runtime.start()
        with pytest.raises(RuntimeError, match="resource discovery failed"):
            await runtime.refresh_resources()
        await runtime.shutdown_worker()
