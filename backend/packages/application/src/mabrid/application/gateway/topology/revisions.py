"""Immutable managed topology revisions selected for bridge sessions."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from mabrid.bridge import (
    BindingPlan,
    BridgeCapabilities,
    EndpointMode,
    EndpointPlan,
    SseUpstreamConfig,
    StdioUpstreamConfig,
    StreamableHttpUpstreamConfig,
    UpstreamConfig,
)
from pydantic import ConfigDict, Field, PositiveInt, model_validator

from .models import ServiceModel, UpstreamConnection


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UpstreamRevision(ServiceModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    revision_id: UUID = Field(default_factory=uuid4)
    server_id: UUID
    revision_number: PositiveInt = 1
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    display_name: str = Field(min_length=1)
    connection: UpstreamConnection
    enabled: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class EndpointBindingRevision(ServiceModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    binding_revision_id: UUID = Field(default_factory=uuid4)
    binding_id: UUID = Field(default_factory=uuid4)
    namespace: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]*$")
    priority: int = 0
    enabled: bool = True
    upstream: UpstreamRevision


class EndpointTopologyRevision(ServiceModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    revision_id: UUID = Field(default_factory=uuid4)
    endpoint_id: UUID
    revision_number: PositiveInt = 1
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    display_name: str = Field(min_length=1)
    mode: EndpointMode = EndpointMode.PASSTHROUGH
    bindings: tuple[EndpointBindingRevision, ...]
    enabled: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_bindings(self) -> EndpointTopologyRevision:
        active_bindings = [binding for binding in self.bindings if binding.enabled]
        if self.mode is EndpointMode.PASSTHROUGH:
            if len(active_bindings) != 1:
                raise ValueError("passthrough revisions require exactly one enabled binding")
            if active_bindings[0].namespace is not None:
                raise ValueError("passthrough revision bindings cannot define a namespace")
            return self

        if not active_bindings:
            raise ValueError("aggregate revisions require at least one enabled binding")
        namespaces = [binding.namespace for binding in active_bindings]
        if any(namespace is None for namespace in namespaces):
            raise ValueError("aggregate revision bindings require namespaces")
        if len(namespaces) != len(set(namespaces)):
            raise ValueError("aggregate revision binding namespaces must be unique")
        return self


def build_endpoint_plan_from_revision(revision: EndpointTopologyRevision) -> EndpointPlan:
    """Convert one persisted topology revision into the core runtime contract."""
    if not revision.enabled:
        raise ValueError(f"cannot build a plan for disabled endpoint: {revision.display_name}")

    bindings: list[BindingPlan] = []
    for binding in revision.bindings:
        if not binding.enabled:
            continue
        upstream = binding.upstream
        if not upstream.enabled:
            raise ValueError(
                f"enabled binding references disabled upstream: {binding.binding_revision_id}"
            )
        bindings.append(
            BindingPlan(
                binding_key=str(binding.binding_revision_id),
                upstream_key=str(upstream.revision_id),
                upstream_name=upstream.display_name,
                namespace=binding.namespace,
                priority=binding.priority,
                upstream=_to_upstream_config(upstream.connection),
            )
        )

    return EndpointPlan(
        endpoint_key=str(revision.revision_id),
        display_name=revision.display_name,
        mode=revision.mode,
        bindings=tuple(bindings),
        capabilities=BridgeCapabilities(tools=True, resources=True),
    )


def _to_upstream_config(connection: UpstreamConnection) -> UpstreamConfig:
    if connection.transport == "stdio":
        return StdioUpstreamConfig(
            command=connection.command,
            args=tuple(connection.args),
            cwd=connection.cwd,
            env=connection.env,
        )
    if connection.transport == "sse":
        return SseUpstreamConfig(url=connection.url, headers=connection.headers)
    return StreamableHttpUpstreamConfig(
        url=connection.url,
        headers=connection.headers,
        timeout_seconds=connection.timeout_seconds,
    )
