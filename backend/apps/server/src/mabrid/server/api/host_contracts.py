"""First-party Host HTTP contracts excluding deployment and routing identifiers."""

from typing import Literal, Annotated
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    JsonValue,
)
from mabrid.application.agent_host import TokenUsage, AgentSessionRunStatus


class HostHttpModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CreateHostSessionRequest(HostHttpModel):
    title: str | None = None


class HostSessionResponse(HostHttpModel):
    session_id: UUID
    target_id: str = Field(min_length=1)
    title: str | None = None
    created_at: AwareDatetime
    binding_state: Literal["unknown", "available", "missing", "runtime_changed", "unavailable"]
    target_run: AgentSessionRunStatus | None = None


class HostSessionPageResponse(HostHttpModel):
    sessions: tuple[HostSessionResponse, ...]
    limit: int = Field(ge=1, le=200)
    offset: NonNegativeInt
    has_more: bool


class StartHostSessionRunRequest(HostHttpModel):
    input_text: str = Field(min_length=1, pattern=r"\S")


class HostErrorResponse(HostHttpModel):
    code: Literal[
        "invalid_request",
        "run_not_found",
        "internal_error",
        "session_not_found",
        "remote_session_not_found",
        "runtime_binding_changed",
        "runtime_unavailable",
        "runtime_contract_error",
        "target_busy",
        "unsupported_operation",
        "run_state_unknown",
    ]
    message: str
    session_id: UUID | None = None
    run_id: UUID | None = None


class HostStopResponse(HostHttpModel):
    session_id: UUID
    run_id: UUID
    accepted: bool
    settlement: Literal["unconfirmed"] = "unconfirmed"


class HostReconcileResponse(HostHttpModel):
    session_id: UUID
    run_id: UUID
    settled: bool


class HostToolResult(HostHttpModel):
    content: tuple[dict[str, JsonValue], ...] = ()
    structured_content: dict[str, JsonValue] | None = None
    is_error: bool = False
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class HostResourceContent(HostHttpModel):
    uri: str
    mime_type: str | None = None
    text: str | None = None
    blob: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class HostWidget(HostHttpModel):
    widget_id: UUID
    tool_invocation_id: UUID
    tool_name: str
    tool_result: HostToolResult
    application_resource_uri: str
    resource_contents: tuple[HostResourceContent, ...]
    resource_metadata: dict[str, JsonValue]


class HostRunStartedPayload(HostHttpModel):
    kind: Literal["run.started"] = "run.started"
    target_id: str


class HostTextDeltaPayload(HostHttpModel):
    kind: Literal["assistant.text.delta"] = "assistant.text.delta"
    delta: str


class HostTextCompletedPayload(HostHttpModel):
    kind: Literal["assistant.text.completed"] = "assistant.text.completed"
    text: str


class HostRunCompletedPayload(HostHttpModel):
    kind: Literal["run.completed"] = "run.completed"
    output_text: str
    usage: TokenUsage


class HostRunCancelledPayload(HostHttpModel):
    kind: Literal["run.cancelled"] = "run.cancelled"


class HostRunFailedPayload(HostHttpModel):
    kind: Literal["run.failed"] = "run.failed"
    error: HostErrorResponse


class HostToolStartedPayload(HostHttpModel):
    kind: Literal["tool.started"] = "tool.started"
    tool_invocation_id: UUID
    tool_name: str
    arguments: dict[str, JsonValue]


class HostToolCompletedPayload(HostHttpModel):
    kind: Literal["tool.completed"] = "tool.completed"
    tool_invocation_id: UUID
    tool_name: str
    result: HostToolResult


class HostToolFailedPayload(HostHttpModel):
    kind: Literal["tool.failed"] = "tool.failed"
    tool_invocation_id: UUID
    tool_name: str
    error_code: str
    error_message: str
    result: HostToolResult | None = None


class HostWidgetCreatedPayload(HostHttpModel):
    kind: Literal["widget.created"] = "widget.created"
    widget: HostWidget


class HostWidgetFailedPayload(HostHttpModel):
    kind: Literal["widget.failed"] = "widget.failed"
    tool_invocation_id: UUID
    tool_name: str
    tool_result: HostToolResult
    application_resource_uri: str
    error_message: str


HostStreamPayload = Annotated[
    HostRunStartedPayload
    | HostTextDeltaPayload
    | HostTextCompletedPayload
    | HostRunCompletedPayload
    | HostRunCancelledPayload
    | HostRunFailedPayload
    | HostToolStartedPayload
    | HostToolCompletedPayload
    | HostToolFailedPayload
    | HostWidgetCreatedPayload
    | HostWidgetFailedPayload,
    Field(discriminator="kind"),
]


class HostStreamEvent(HostHttpModel):
    event_id: UUID
    session_id: UUID
    run_id: UUID
    sequence: PositiveInt
    created_at: AwareDatetime
    event: HostStreamPayload
