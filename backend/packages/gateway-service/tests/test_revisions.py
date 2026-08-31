from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import AnyHttpUrl

from mcp_gateway_service import (
    EndpointBindingRevision,
    EndpointMode,
    EndpointTopologyRevision,
    SseConnection,
    StdioConnection,
    StreamableHttpConnection,
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


def test_revision_plan_preserves_transports_and_skips_disabled_bindings() -> None:
    stdio = UpstreamRevision(
        server_id=uuid4(),
        slug="local",
        display_name="Local",
        connection=StdioConnection(
            command="fixture-server",
            args=["--stdio"],
            cwd=Path("fixtures"),
            env={"MODE": "test"},
        ),
    )
    sse = UpstreamRevision(
        server_id=uuid4(),
        slug="legacy",
        display_name="Legacy",
        connection=SseConnection(
            url=AnyHttpUrl("https://example.test/sse"),
            headers={"X-Test": "sse"},
        ),
    )
    http = UpstreamRevision(
        server_id=uuid4(),
        slug="remote",
        display_name="Remote",
        connection=StreamableHttpConnection(
            url=AnyHttpUrl("https://example.test/mcp"),
            headers={"X-Test": "http"},
            timeout_seconds=18,
        ),
    )
    revision = EndpointTopologyRevision(
        endpoint_id=uuid4(),
        slug="all",
        display_name="All Tools",
        mode=EndpointMode.AGGREGATE,
        bindings=(
            EndpointBindingRevision(namespace="local", upstream=stdio),
            EndpointBindingRevision(namespace="legacy", upstream=sse),
            EndpointBindingRevision(namespace="remote", upstream=http),
            EndpointBindingRevision(namespace="disabled", upstream=http, enabled=False),
        ),
    )

    plan = build_endpoint_plan_from_revision(revision)

    assert [binding.upstream.transport for binding in plan.bindings] == [
        "stdio",
        "sse",
        "streamable-http",
    ]
    assert plan.bindings[0].upstream.cwd == Path("fixtures")
    assert plan.bindings[2].upstream.timeout_seconds == 18


def test_revision_plan_rejects_disabled_publication() -> None:
    upstream = UpstreamRevision(
        server_id=uuid4(),
        slug="fixture",
        display_name="Fixture",
        connection=StdioConnection(command="fixture-server"),
    )
    revision = EndpointTopologyRevision(
        endpoint_id=uuid4(),
        slug="fixture",
        display_name="Fixture",
        bindings=(EndpointBindingRevision(upstream=upstream),),
        enabled=False,
    )

    with pytest.raises(ValueError, match="disabled endpoint"):
        build_endpoint_plan_from_revision(revision)

    enabled_revision = revision.model_copy(
        update={
            "enabled": True,
            "bindings": (
                EndpointBindingRevision(
                    upstream=upstream.model_copy(update={"enabled": False})
                ),
            ),
        }
    )
    with pytest.raises(ValueError, match="disabled upstream"):
        build_endpoint_plan_from_revision(enabled_revision)
