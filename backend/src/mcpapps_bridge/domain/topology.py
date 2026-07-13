"""Domain models for managed upstream servers and published MCP endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, PositiveFloat, model_validator
from enum import StrEnum


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EndpointMode(StrEnum):
    PASSTHROUGH = "passthrough"
    AGGREGATE = "aggregate"


class UpstreamSessionMode(StrEnum):
    ISOLATED = "isolated"
    SHARED = "shared"


class StreamableHttpConnection(DomainModel):
    transport: Literal["streamable-http"] = "streamable-http"
    url: AnyHttpUrl
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: PositiveFloat = 30.0


class SseConnection(DomainModel):
    transport: Literal["sse"] = "sse"
    url: AnyHttpUrl
    headers: dict[str, str] = Field(default_factory=dict)


class StdioConnection(DomainModel):
    transport: Literal["stdio"] = "stdio"
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    cwd: Path | None = None
    env: dict[str, str] = Field(default_factory=dict)


UpstreamConnection = Annotated[
    StreamableHttpConnection | SseConnection | StdioConnection,
    Field(discriminator="transport"),
]


class UpstreamServerDefinition(DomainModel):
    server_id: UUID = Field(default_factory=uuid4)
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    display_name: str = Field(min_length=1)
    connection: UpstreamConnection
    enabled: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)


class EndpointSessionPolicy(DomainModel):
    upstream_session_mode: UpstreamSessionMode = UpstreamSessionMode.ISOLATED
    lazy_upstream_connections: bool = True
    idle_timeout_seconds: PositiveFloat = 900.0


class EndpointBinding(DomainModel):
    binding_id: UUID = Field(default_factory=uuid4)
    upstream_server_id: UUID
    namespace: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]*$")
    priority: int = 0
    enabled: bool = True


class EndpointDefinition(DomainModel):
    endpoint_id: UUID = Field(default_factory=uuid4)
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    display_name: str = Field(min_length=1)
    mode: EndpointMode = EndpointMode.PASSTHROUGH
    bindings: list[EndpointBinding]
    session_policy: EndpointSessionPolicy = Field(default_factory=EndpointSessionPolicy)
    enabled: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)

    @property
    def path(self) -> str:
        return f"/mcp/{self.slug}"

    @model_validator(mode="after")
    def validate_bindings(self) -> EndpointDefinition:
        active_bindings = [binding for binding in self.bindings if binding.enabled]
        if self.mode is EndpointMode.PASSTHROUGH:
            if len(active_bindings) != 1:
                raise ValueError("passthrough endpoints require exactly one enabled binding")
            if active_bindings[0].namespace is not None:
                raise ValueError("passthrough endpoint bindings cannot define a namespace")
            return self

        if not active_bindings:
            raise ValueError("aggregate endpoints require at least one enabled binding")
        namespaces = [binding.namespace for binding in active_bindings]
        if any(namespace is None for namespace in namespaces):
            raise ValueError("aggregate endpoint bindings require namespaces")
        if len(namespaces) != len(set(namespaces)):
            raise ValueError("aggregate endpoint binding namespaces must be unique")
        return self
