from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_bridge_core import (
    BindingPlan,
    BridgeCapabilities,
    BridgeObservation,
    BridgeSessionStarted,
    EndpointMode,
    EndpointPlan,
    StdioUpstreamConfig,
    ToolsPublished,
    UpstreamIdentity,
)


def binding(namespace: str | None) -> BindingPlan:
    return BindingPlan(
        binding_key="binding-1",
        upstream_key="upstream-1",
        upstream_name="Fixture Upstream",
        namespace=namespace,
        upstream=StdioUpstreamConfig(command="fixture-server"),
    )


def test_endpoint_plan_enforces_routing_shape() -> None:
    passthrough = EndpointPlan(
        endpoint_key="endpoint-1",
        display_name="Fixture",
        mode=EndpointMode.PASSTHROUGH,
        bindings=(binding(None),),
        capabilities=BridgeCapabilities(tools=True, resources=True),
    )
    assert passthrough.bindings[0].namespace is None

    aggregate = EndpointPlan(
        endpoint_key="endpoint-2",
        display_name="Aggregate",
        mode=EndpointMode.AGGREGATE,
        bindings=(binding("docs"),),
        capabilities=BridgeCapabilities(tools=True, resources=True),
    )
    assert aggregate.bindings[0].namespace == "docs"

    with pytest.raises(ValidationError, match="aggregate plan bindings require namespaces"):
        EndpointPlan(
            endpoint_key="endpoint-3",
            display_name="Invalid Aggregate",
            mode=EndpointMode.AGGREGATE,
            bindings=(binding(None),),
            capabilities=BridgeCapabilities(tools=True),
        )


def test_observation_union_uses_stable_discriminator() -> None:
    adapter = TypeAdapter(BridgeObservation)
    started = BridgeSessionStarted(
        session_key="session-1",
        identity=UpstreamIdentity(
            server_name="fixture-server",
            protocol_version="2025-11-25",
        ),
    )
    restored = adapter.validate_json(started.model_dump_json())
    assert isinstance(restored, BridgeSessionStarted)

    published = ToolsPublished(session_key="session-1", tools=())
    restored = adapter.validate_python(published.model_dump(mode="python"))
    assert isinstance(restored, ToolsPublished)
