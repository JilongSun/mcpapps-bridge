"""Immutable managed topology revisions used to build session routing plans."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import ConfigDict, Field, PositiveInt, model_validator

from .topology import DomainModel, EndpointMode, EndpointSessionPolicy, UpstreamConnection


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UpstreamRevision(DomainModel):
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


class EndpointBindingRevision(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    binding_revision_id: UUID = Field(default_factory=uuid4)
    binding_id: UUID = Field(default_factory=uuid4)
    namespace: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]*$")
    priority: int = 0
    enabled: bool = True
    upstream: UpstreamRevision


class EndpointTopologyRevision(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    revision_id: UUID = Field(default_factory=uuid4)
    endpoint_id: UUID
    revision_number: PositiveInt = 1
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    display_name: str = Field(min_length=1)
    mode: EndpointMode = EndpointMode.PASSTHROUGH
    bindings: tuple[EndpointBindingRevision, ...]
    session_policy: EndpointSessionPolicy = Field(default_factory=EndpointSessionPolicy)
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
