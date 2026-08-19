"""Transitional managed-revision adapter for the bridge-core plan contract."""

from __future__ import annotations

from mcp_bridge_core import EndpointMode, EndpointPlan
from mcp_gateway_service import (
    ResolvedBindingRevision,
    ResolvedEndpointRevision,
    ResolvedSseConnection,
    ResolvedStdioConnection,
    ResolvedStreamableHttpConnection,
    ResolvedUpstreamRevision,
    build_endpoint_plan,
)

from mcpapps_bridge.domain import (
    EndpointTopologyRevision,
    SseConnection,
    StdioConnection,
    StreamableHttpConnection,
    UpstreamConnection,
)


def endpoint_plan_from_revision(revision: EndpointTopologyRevision) -> EndpointPlan:
    """Adapt the current monolith domain model without leaking it into new packages."""
    resolved_bindings = tuple(
        ResolvedBindingRevision(
            binding_revision_key=str(binding.binding_revision_id),
            namespace=binding.namespace,
            priority=binding.priority,
            enabled=binding.enabled,
            upstream=ResolvedUpstreamRevision(
                upstream_revision_key=str(binding.upstream.revision_id),
                display_name=binding.upstream.display_name,
                enabled=binding.upstream.enabled,
                connection=_resolved_connection(binding.upstream.connection),
            ),
        )
        for binding in revision.bindings
    )
    return build_endpoint_plan(
        ResolvedEndpointRevision(
            endpoint_revision_key=str(revision.revision_id),
            display_name=revision.display_name,
            mode=EndpointMode(revision.mode.value),
            bindings=resolved_bindings,
            enabled=revision.enabled,
        )
    )


def _resolved_connection(
    connection: UpstreamConnection,
) -> ResolvedStdioConnection | ResolvedSseConnection | ResolvedStreamableHttpConnection:
    if isinstance(connection, StdioConnection):
        return ResolvedStdioConnection(
            command=connection.command,
            args=tuple(connection.args),
            cwd=connection.cwd,
            env=connection.env,
        )
    if isinstance(connection, SseConnection):
        return ResolvedSseConnection(
            url=connection.url,
            headers=connection.headers,
        )
    if isinstance(connection, StreamableHttpConnection):
        return ResolvedStreamableHttpConnection(
            url=connection.url,
            headers=connection.headers,
            timeout_seconds=connection.timeout_seconds,
        )
    raise TypeError(f"Unsupported upstream connection: {type(connection).__name__}")
