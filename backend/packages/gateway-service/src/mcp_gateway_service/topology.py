"""Resolved managed topology and bridge-core plan conversion."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from mcp_bridge_core import (
    BindingPlan,
    BridgeCapabilities,
    EndpointMode,
    EndpointPlan,
    SseUpstreamConfig,
    StdioUpstreamConfig,
    StreamableHttpUpstreamConfig,
    UpstreamConfig,
)
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, PositiveFloat


class ResolvedTopologyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResolvedStdioConnection(ResolvedTopologyModel):
    transport: Literal["stdio"] = "stdio"
    command: str = Field(min_length=1)
    args: tuple[str, ...] = ()
    cwd: Path | None = None
    env: dict[str, str] = Field(default_factory=dict)


class ResolvedSseConnection(ResolvedTopologyModel):
    transport: Literal["sse"] = "sse"
    url: AnyHttpUrl
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: PositiveFloat = 30.0


class ResolvedStreamableHttpConnection(ResolvedTopologyModel):
    transport: Literal["streamable-http"] = "streamable-http"
    url: AnyHttpUrl
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: PositiveFloat = 30.0


ResolvedUpstreamConnection = Annotated[
    ResolvedStdioConnection | ResolvedSseConnection | ResolvedStreamableHttpConnection,
    Field(discriminator="transport"),
]


class ResolvedUpstreamRevision(ResolvedTopologyModel):
    upstream_revision_key: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    enabled: bool = True
    connection: ResolvedUpstreamConnection


class ResolvedBindingRevision(ResolvedTopologyModel):
    binding_revision_key: str = Field(min_length=1)
    namespace: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]*$")
    priority: int = 0
    enabled: bool = True
    upstream: ResolvedUpstreamRevision


class ResolvedEndpointRevision(ResolvedTopologyModel):
    endpoint_revision_key: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    mode: EndpointMode
    bindings: tuple[ResolvedBindingRevision, ...]
    capabilities: BridgeCapabilities = Field(
        default_factory=lambda: BridgeCapabilities(tools=True, resources=True)
    )
    enabled: bool = True


def build_endpoint_plan(revision: ResolvedEndpointRevision) -> EndpointPlan:
    """Convert one complete managed revision into an immutable core runtime plan."""
    if not revision.enabled:
        raise ValueError(f"cannot build a plan for disabled endpoint: {revision.display_name}")

    bindings: list[BindingPlan] = []
    for binding in revision.bindings:
        if not binding.enabled:
            continue
        if not binding.upstream.enabled:
            raise ValueError(
                f"enabled binding references disabled upstream: {binding.binding_revision_key}"
            )
        bindings.append(
            BindingPlan(
                binding_key=binding.binding_revision_key,
                upstream_key=binding.upstream.upstream_revision_key,
                upstream_name=binding.upstream.display_name,
                namespace=binding.namespace,
                priority=binding.priority,
                upstream=_to_upstream_config(binding.upstream.connection),
            )
        )

    return EndpointPlan(
        endpoint_key=revision.endpoint_revision_key,
        display_name=revision.display_name,
        mode=revision.mode,
        bindings=tuple(bindings),
        capabilities=revision.capabilities,
    )


def _to_upstream_config(connection: ResolvedUpstreamConnection) -> UpstreamConfig:
    if isinstance(connection, ResolvedStdioConnection):
        return StdioUpstreamConfig(
            command=connection.command,
            args=connection.args,
            cwd=connection.cwd,
            env=connection.env,
        )
    if isinstance(connection, ResolvedSseConnection):
        return SseUpstreamConfig(
            url=connection.url,
            headers=connection.headers,
            timeout_seconds=connection.timeout_seconds,
        )
    return StreamableHttpUpstreamConfig(
        url=connection.url,
        headers=connection.headers,
        timeout_seconds=connection.timeout_seconds,
    )
