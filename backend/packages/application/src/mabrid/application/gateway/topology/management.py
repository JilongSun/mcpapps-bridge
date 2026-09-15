"""Read models for inspecting current managed topology without runtime secrets."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from mabrid.bridge import EndpointMode
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt


class ManagementReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ConfiguredKey(ManagementReadModel):
    name: str = Field(min_length=1)
    configured: Literal[True] = True


class ManagedStreamableHttpConnection(ManagementReadModel):
    transport: Literal["streamable-http"] = "streamable-http"
    url: AnyHttpUrl
    headers: tuple[ConfiguredKey, ...] = ()
    timeout_seconds: PositiveFloat = 30.0


class ManagedSseConnection(ManagementReadModel):
    transport: Literal["sse"] = "sse"
    url: AnyHttpUrl
    headers: tuple[ConfiguredKey, ...] = ()


class ManagedStdioConnection(ManagementReadModel):
    transport: Literal["stdio"] = "stdio"
    command: str = Field(min_length=1)
    args: tuple[str, ...] = ()
    cwd: Path | None = None
    env: tuple[ConfiguredKey, ...] = ()


ManagedUpstreamConnection = Annotated[
    ManagedStreamableHttpConnection | ManagedSseConnection | ManagedStdioConnection,
    Field(discriminator="transport"),
]


class RevisionMetadata(ManagementReadModel):
    revision_id: UUID
    revision_number: PositiveInt
    created_at: datetime


class ManagedUpstream(ManagementReadModel):
    server_id: UUID
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    display_name: str = Field(min_length=1)
    connection: ManagedUpstreamConnection
    enabled: bool
    metadata: dict[str, object] = Field(default_factory=dict)
    current_revision: RevisionMetadata


class ManagedEndpointBinding(ManagementReadModel):
    binding_id: UUID
    binding_revision_id: UUID
    upstream_server_id: UUID
    upstream_revision_id: UUID
    namespace: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]*$")
    priority: int = 0
    enabled: bool = True


class ManagedEndpoint(ManagementReadModel):
    endpoint_id: UUID
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    display_name: str = Field(min_length=1)
    mode: EndpointMode
    bindings: tuple[ManagedEndpointBinding, ...]
    enabled: bool
    metadata: dict[str, object] = Field(default_factory=dict)
    current_revision: RevisionMetadata


class TopologySnapshot(ManagementReadModel):
    upstreams: tuple[ManagedUpstream, ...]
    endpoints: tuple[ManagedEndpoint, ...]
