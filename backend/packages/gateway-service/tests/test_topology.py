from __future__ import annotations

from pathlib import Path

import pytest
from mcp_bridge_core import EndpointMode
from pydantic import AnyHttpUrl

from mcp_gateway_service import (
    ResolvedBindingRevision,
    ResolvedEndpointRevision,
    ResolvedSseConnection,
    ResolvedStdioConnection,
    ResolvedStreamableHttpConnection,
    ResolvedUpstreamRevision,
    build_endpoint_plan,
)


def upstream(
    key: str,
    connection: (
        ResolvedStdioConnection | ResolvedSseConnection | ResolvedStreamableHttpConnection
    ),
    *,
    enabled: bool = True,
) -> ResolvedUpstreamRevision:
    return ResolvedUpstreamRevision(
        upstream_revision_key=key,
        display_name=f"Fixture {key}",
        enabled=enabled,
        connection=connection,
    )


def binding(
    key: str,
    namespace: str,
    upstream_revision: ResolvedUpstreamRevision,
    *,
    enabled: bool = True,
) -> ResolvedBindingRevision:
    return ResolvedBindingRevision(
        binding_revision_key=key,
        namespace=namespace,
        priority=10,
        enabled=enabled,
        upstream=upstream_revision,
    )


def test_build_endpoint_plan_preserves_resolved_transport_and_revision_keys() -> None:
    revision = ResolvedEndpointRevision(
        endpoint_revision_key="endpoint-revision-7",
        display_name="All Tools",
        mode=EndpointMode.AGGREGATE,
        bindings=(
            binding(
                "binding-stdio",
                "local",
                upstream(
                    "upstream-stdio",
                    ResolvedStdioConnection(
                        command="fixture-server",
                        args=("--stdio",),
                        cwd=Path("fixtures"),
                        env={"MODE": "test"},
                    ),
                ),
            ),
            binding(
                "binding-sse",
                "legacy",
                upstream(
                    "upstream-sse",
                    ResolvedSseConnection(
                        url=AnyHttpUrl("https://example.test/sse"),
                        headers={"X-Test": "sse"},
                        timeout_seconds=12,
                    ),
                ),
            ),
            binding(
                "binding-http",
                "remote",
                upstream(
                    "upstream-http",
                    ResolvedStreamableHttpConnection(
                        url=AnyHttpUrl("https://example.test/mcp"),
                        headers={"X-Test": "http"},
                        timeout_seconds=18,
                    ),
                ),
            ),
            binding(
                "binding-disabled",
                "disabled",
                upstream(
                    "upstream-disabled-binding",
                    ResolvedStdioConnection(command="ignored"),
                ),
                enabled=False,
            ),
        ),
    )

    plan = build_endpoint_plan(revision)

    assert plan.endpoint_key == "endpoint-revision-7"
    assert plan.capabilities.tools is True
    assert plan.capabilities.resources is True
    assert [item.binding_key for item in plan.bindings] == [
        "binding-stdio",
        "binding-sse",
        "binding-http",
    ]
    assert [item.upstream_key for item in plan.bindings] == [
        "upstream-stdio",
        "upstream-sse",
        "upstream-http",
    ]
    assert [item.upstream_name for item in plan.bindings] == [
        "Fixture upstream-stdio",
        "Fixture upstream-sse",
        "Fixture upstream-http",
    ]
    assert plan.bindings[0].upstream.transport == "stdio"
    assert plan.bindings[1].upstream.transport == "sse"
    assert plan.bindings[2].upstream.transport == "streamable-http"


def test_build_endpoint_plan_rejects_disabled_publication() -> None:
    endpoint = ResolvedEndpointRevision(
        endpoint_revision_key="endpoint-disabled",
        display_name="Disabled",
        mode=EndpointMode.PASSTHROUGH,
        bindings=(
            ResolvedBindingRevision(
                binding_revision_key="binding-1",
                upstream=upstream(
                    "upstream-1",
                    ResolvedStdioConnection(command="fixture-server"),
                ),
            ),
        ),
        enabled=False,
    )
    with pytest.raises(ValueError, match="disabled endpoint"):
        build_endpoint_plan(endpoint)

    enabled_endpoint = endpoint.model_copy(
        update={
            "enabled": True,
            "bindings": (
                ResolvedBindingRevision(
                    binding_revision_key="binding-1",
                    upstream=upstream(
                        "upstream-1",
                        ResolvedStdioConnection(command="fixture-server"),
                        enabled=False,
                    ),
                ),
            ),
        }
    )
    with pytest.raises(ValueError, match="disabled upstream"):
        build_endpoint_plan(enabled_endpoint)
