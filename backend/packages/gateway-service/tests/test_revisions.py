from __future__ import annotations

from uuid import uuid4

from mcp_gateway_service import (
    EndpointBindingRevision,
    EndpointMode,
    EndpointTopologyRevision,
    StdioConnection,
    UpstreamRevision,
    build_endpoint_plan_from_revision,
)


def test_revision_builds_core_plan_with_immutable_revision_keys() -> None:
    upstream = UpstreamRevision(
        server_id=uuid4(),
        slug="fixture",
        display_name="Fixture",
        connection=StdioConnection(command="fixture-server", args=["--stdio"]),
    )
    binding = EndpointBindingRevision(namespace="fixture", upstream=upstream)
    revision = EndpointTopologyRevision(
        endpoint_id=uuid4(),
        slug="all",
        display_name="All Tools",
        mode=EndpointMode.AGGREGATE,
        bindings=(binding,),
    )

    plan = build_endpoint_plan_from_revision(revision)

    assert plan.endpoint_key == str(revision.revision_id)
    assert plan.mode.value == revision.mode.value
    assert plan.bindings[0].binding_key == str(binding.binding_revision_id)
    assert plan.bindings[0].upstream_key == str(upstream.revision_id)
    assert plan.bindings[0].namespace == "fixture"
    assert plan.bindings[0].upstream.transport == "stdio"
    assert plan.bindings[0].upstream.args == ("--stdio",)
