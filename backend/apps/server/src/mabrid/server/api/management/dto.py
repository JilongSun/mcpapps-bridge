"""Server-owned response DTOs for the read-only management HTTP contract."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from mabrid.application.agent_host import AgentTarget
from mabrid.application.gateway.inspection import (
    BridgeSessionSnapshot,
    SequencedSessionEvent,
)
from mabrid.application.gateway.sessions import BridgeSessionRecord
from mabrid.application.gateway.topology import (
    ManagedEndpoint,
    ManagedSseConnection,
    ManagedStdioConnection,
    ManagedStreamableHttpConnection,
    ManagedUpstream,
    RevisionMetadata,
    TopologySnapshot,
)
from mabrid.bridge import EndpointMode
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from mabrid.server.composition import AgentHostManagementView
from mabrid.server.config import build_advertised_mcp_url


class ManagementResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ConfiguredKeyResponse(ManagementResponse):
    name: str
    configured: Literal[True]


class StreamableHttpConnectionResponse(ManagementResponse):
    transport: Literal["streamable-http"]
    url: str
    headers: tuple[ConfiguredKeyResponse, ...]
    timeout_seconds: float


class SseConnectionResponse(ManagementResponse):
    transport: Literal["sse"]
    url: str
    headers: tuple[ConfiguredKeyResponse, ...]


class StdioConnectionResponse(ManagementResponse):
    transport: Literal["stdio"]
    command: str
    args: tuple[str, ...]
    cwd: str | None
    env: tuple[ConfiguredKeyResponse, ...]


UpstreamConnectionResponse = Annotated[
    StreamableHttpConnectionResponse | SseConnectionResponse | StdioConnectionResponse,
    Field(discriminator="transport"),
]


class RevisionMetadataResponse(ManagementResponse):
    revision_id: UUID
    revision_number: int
    created_at: datetime

    @classmethod
    def from_model(cls, value: RevisionMetadata) -> RevisionMetadataResponse:
        return cls.model_validate(value.model_dump())


class ManagedUpstreamResponse(ManagementResponse):
    server_id: UUID
    slug: str
    display_name: str
    connection: UpstreamConnectionResponse
    enabled: bool
    metadata: dict[str, object]
    current_revision: RevisionMetadataResponse

    @classmethod
    def from_model(cls, value: ManagedUpstream) -> ManagedUpstreamResponse:
        connection: UpstreamConnectionResponse
        if isinstance(value.connection, ManagedStreamableHttpConnection):
            connection = StreamableHttpConnectionResponse.model_validate(
                value.connection.model_dump(mode="json")
            )
        elif isinstance(value.connection, ManagedSseConnection):
            connection = SseConnectionResponse.model_validate(
                value.connection.model_dump(mode="json")
            )
        elif isinstance(value.connection, ManagedStdioConnection):
            connection = StdioConnectionResponse.model_validate(
                value.connection.model_dump(mode="json")
            )
        return cls(
            server_id=value.server_id,
            slug=value.slug,
            display_name=value.display_name,
            connection=connection,
            enabled=value.enabled,
            metadata=value.metadata,
            current_revision=RevisionMetadataResponse.from_model(value.current_revision),
        )


class ManagedEndpointBindingResponse(ManagementResponse):
    binding_id: UUID
    binding_revision_id: UUID
    upstream_server_id: UUID
    upstream_revision_id: UUID
    namespace: str | None
    priority: int
    enabled: bool


class ManagedEndpointResponse(ManagementResponse):
    endpoint_id: UUID
    slug: str
    display_name: str
    mode: EndpointMode
    bindings: tuple[ManagedEndpointBindingResponse, ...]
    enabled: bool
    metadata: dict[str, object]
    current_revision: RevisionMetadataResponse
    endpoint_path: str
    advertised_url: str | None

    @classmethod
    def from_model(
        cls,
        value: ManagedEndpoint,
        advertised_base_url: str | None,
    ) -> ManagedEndpointResponse:
        return cls(
            endpoint_id=value.endpoint_id,
            slug=value.slug,
            display_name=value.display_name,
            mode=value.mode,
            bindings=tuple(
                ManagedEndpointBindingResponse.model_validate(binding.model_dump())
                for binding in value.bindings
            ),
            enabled=value.enabled,
            metadata=value.metadata,
            current_revision=RevisionMetadataResponse.from_model(value.current_revision),
            endpoint_path=f"/mcp/{value.slug}",
            advertised_url=(
                build_advertised_mcp_url(advertised_base_url, value.slug)
                if advertised_base_url is not None
                else None
            ),
        )


class TopologyResponse(ManagementResponse):
    advertised_base_url: str | None
    upstreams: tuple[ManagedUpstreamResponse, ...]
    endpoints: tuple[ManagedEndpointResponse, ...]

    @classmethod
    def from_model(
        cls,
        value: TopologySnapshot,
        advertised_base_url: str | None,
    ) -> TopologyResponse:
        return cls(
            advertised_base_url=advertised_base_url,
            upstreams=tuple(ManagedUpstreamResponse.from_model(item) for item in value.upstreams),
            endpoints=tuple(
                ManagedEndpointResponse.from_model(item, advertised_base_url)
                for item in value.endpoints
            ),
        )


class GatewayStatusResponse(ManagementResponse):
    version: str
    lifecycle_state: Literal["running"] = "running"
    topology_mode: Literal["frozen_seeded"] = "frozen_seeded"
    advertised_base_url: str | None
    published_endpoint_count: int
    published_endpoint_slugs: tuple[str, ...]


class SessionResponse(ManagementResponse):
    session_id: UUID
    endpoint_id: UUID
    endpoint_revision_id: UUID
    status: str
    created_at: datetime
    last_activity_at: datetime
    closed_at: datetime | None
    error_message: str | None

    @classmethod
    def from_model(cls, value: BridgeSessionRecord) -> SessionResponse:
        return cls.model_validate(value.model_dump())


class SessionPageResponse(ManagementResponse):
    items: tuple[SessionResponse, ...]
    next_cursor: str | None


class UpstreamInitializationResponse(ManagementResponse):
    server_name: str
    server_version: str | None = None
    protocol_version: str | None = None
    instructions: str | None = None
    supports_tools: bool = True
    supports_resources: bool = False
    raw_capabilities: dict[str, Any] = Field(default_factory=dict)


class ToolDescriptorResponse(ManagementResponse):
    name: str
    title: str | None = None
    description: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    annotations: dict[str, Any] = Field(default_factory=dict)
    ui_resource_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCallResultResponse(ManagementResponse):
    content: list[dict[str, Any]] = Field(default_factory=list)
    structured_content: dict[str, Any] | None = None
    is_error: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCallRecordResponse(ManagementResponse):
    call_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: str
    result: ToolCallResultResponse | None = None
    started_at: datetime
    completed_at: datetime | None = None


class ResourceContentResponse(ManagementResponse):
    uri: str
    mime_type: str | None = None
    text: str | None = None
    blob: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResourceReadRecordResponse(ManagementResponse):
    requested_uri: str
    contents: list[ResourceContentResponse]
    metadata: dict[str, Any] = Field(default_factory=dict)
    loaded_at: datetime


class UpstreamAvailabilityResponse(ManagementResponse):
    binding_revision_id: str
    namespace: str | None = None
    upstream_revision_id: str
    upstream_server_id: str
    status: str
    identity: UpstreamInitializationResponse | None = None
    failure_kind: str | None = None
    error_message: str | None = None
    updated_at: datetime


class SessionSnapshotResponse(ManagementResponse):
    session_id: str
    status: str
    upstream: UpstreamInitializationResponse | None
    upstream_availability: list[UpstreamAvailabilityResponse]
    discovered_tools: list[ToolDescriptorResponse]
    active_tool_calls: list[ToolCallRecordResponse]
    resource_reads: list[ResourceReadRecordResponse]
    last_error: str | None
    event_count: int
    updated_at: datetime

    @classmethod
    def from_model(cls, value: BridgeSessionSnapshot) -> SessionSnapshotResponse:
        return cls.model_validate(value.model_dump())


class BaseSessionEventResponse(ManagementResponse):
    event_id: str
    session_id: str
    created_at: datetime


class SessionStartedEventResponse(BaseSessionEventResponse):
    kind: Literal["session.started"]
    upstream: UpstreamInitializationResponse | None = None


class ToolDiscoveredEventResponse(BaseSessionEventResponse):
    kind: Literal["tool.discovered"]
    tool: ToolDescriptorResponse


class ToolCallStartedEventResponse(BaseSessionEventResponse):
    kind: Literal["tool.call.started"]
    call: ToolCallRecordResponse


class ToolCallCompletedEventResponse(BaseSessionEventResponse):
    kind: Literal["tool.call.completed"]
    call: ToolCallRecordResponse


class ResourceReadEventResponse(BaseSessionEventResponse):
    kind: Literal["resource.read"]
    read: ResourceReadRecordResponse


class ErrorRaisedEventResponse(BaseSessionEventResponse):
    kind: Literal["error.raised"]
    message: str
    details: dict[str, Any]


class UpstreamAvailabilityChangedEventResponse(BaseSessionEventResponse):
    kind: Literal["upstream.availability.changed"]
    availability: UpstreamAvailabilityResponse


SessionEventResponse = Annotated[
    SessionStartedEventResponse
    | ToolDiscoveredEventResponse
    | ToolCallStartedEventResponse
    | ToolCallCompletedEventResponse
    | ResourceReadEventResponse
    | ErrorRaisedEventResponse
    | UpstreamAvailabilityChangedEventResponse,
    Field(discriminator="kind"),
]
SESSION_EVENT_RESPONSE_ADAPTER = TypeAdapter(SessionEventResponse)


class SequencedSessionEventResponse(ManagementResponse):
    sequence: int
    event: SessionEventResponse

    @classmethod
    def from_model(cls, value: SequencedSessionEvent) -> SequencedSessionEventResponse:
        return cls(
            sequence=value.sequence,
            event=SESSION_EVENT_RESPONSE_ADAPTER.validate_python(value.event.model_dump()),
        )


class SessionEventPageResponse(ManagementResponse):
    items: tuple[SequencedSessionEventResponse, ...]
    next_after: int | None


class AgentRuntimeProfileResponse(ManagementResponse):
    integration_kind: str
    interface: str
    capabilities: frozenset[str]


class AgentTargetAssignmentResponse(ManagementResponse):
    endpoint_id: UUID
    endpoint_slug: str
    endpoint_path: str
    transport: Literal["streamable-http"]
    advertised_url: str


class AgentTargetResponse(ManagementResponse):
    target_id: str
    runtime_profile: AgentRuntimeProfileResponse
    assignment: AgentTargetAssignmentResponse

    @classmethod
    def from_view(cls, view: AgentHostManagementView) -> AgentTargetResponse:
        target: AgentTarget = view.target
        return cls(
            target_id=target.target_id,
            runtime_profile=AgentRuntimeProfileResponse.model_validate(
                target.runtime_profile.model_dump()
            ),
            assignment=AgentTargetAssignmentResponse(
                endpoint_id=view.endpoint_id,
                endpoint_slug=view.endpoint_slug,
                endpoint_path=view.endpoint_path,
                transport=view.transport,
                advertised_url=view.advertised_url,
            ),
        )


class ReadinessResponse(ManagementResponse):
    status: Literal["ready"] = "ready"
