from __future__ import annotations

from typing import Any

import pytest

from mcp_bridge_core import (
    AppResource,
    BindingPlan,
    BridgeCapabilities,
    BridgeEngine,
    EndpointMode,
    EndpointPlan,
    NoOpBridgeObserver,
    ResourceDescriptor,
    StdioUpstreamConfig,
    ToolCallResult,
    ToolDescriptor,
    UpstreamConfig,
    UpstreamIdentity,
)


class FixtureClient:
    def __init__(self, name: str, closed: list[str]) -> None:
        self.name = name
        self.closed = closed

    async def connect(self, config: UpstreamConfig) -> UpstreamIdentity:
        return UpstreamIdentity(server_name=self.name, server_version="1.0.0")

    async def list_tools(self) -> list[ToolDescriptor]:
        return [ToolDescriptor(name="echo")]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        return ToolCallResult(content=({"type": "text", "text": tool_name},))

    async def list_resources(self) -> list[ResourceDescriptor]:
        return [ResourceDescriptor(name="status", uri="data://status")]

    async def read_resource(self, uri: str) -> AppResource:
        return AppResource(uri=uri, mime_type="text/plain", text="ready")

    async def close(self) -> None:
        self.closed.append(self.name)


class FixtureClientFactory:
    def __init__(self) -> None:
        self.closed: list[str] = []

    def create(self, config: UpstreamConfig) -> FixtureClient:
        assert isinstance(config, StdioUpstreamConfig)
        return FixtureClient(config.command, self.closed)


def create_plan(name: str) -> EndpointPlan:
    return EndpointPlan(
        endpoint_key=f"endpoint-{name}",
        display_name=name,
        mode=EndpointMode.PASSTHROUGH,
        bindings=(
            BindingPlan(
                binding_key=f"binding-{name}",
                upstream_key=f"upstream-{name}",
                upstream_name=name,
                upstream=StdioUpstreamConfig(command=name),
            ),
        ),
        capabilities=BridgeCapabilities(tools=True, resources=True),
    )


async def test_engine_requires_an_active_lifecycle() -> None:
    engine = BridgeEngine(client_factory=FixtureClientFactory())

    with pytest.raises(RuntimeError, match="not running"):
        await engine.open_session(
            session_key="session-1",
            plan=create_plan("first"),
            observer=NoOpBridgeObserver(),
        )


async def test_session_delegates_protocol_methods_and_closes_idempotently() -> None:
    factory = FixtureClientFactory()
    async with BridgeEngine(client_factory=factory) as engine:
        session = await engine.open_session(
            session_key="session-1",
            plan=create_plan("first"),
            observer=NoOpBridgeObserver(),
        )

        assert session.identity.server_name == "first"
        assert [tool.name for tool in await session.list_tools()] == ["echo"]
        assert (await session.call_tool("echo", {})).is_error is False
        assert [resource.uri for resource in await session.list_resources()] == ["data://status"]
        assert (await session.read_resource("data://status")).text == "ready"
        await session.aclose()
        await session.aclose()

    assert factory.closed == ["first"]


async def test_engine_closes_remaining_sessions_in_reverse_order() -> None:
    factory = FixtureClientFactory()

    async with BridgeEngine(client_factory=factory) as engine:
        await engine.open_session(
            session_key="session-1",
            plan=create_plan("first"),
            observer=NoOpBridgeObserver(),
        )
        await engine.open_session(
            session_key="session-2",
            plan=create_plan("second"),
            observer=NoOpBridgeObserver(),
        )

    assert factory.closed == ["second", "first"]
