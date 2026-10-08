"""Agent Session bindings and runtime-owned history presentation contracts."""

from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, JsonValue, NonNegativeInt

from .base import AgentHostModel
from .run import TokenUsage


class RuntimeSessionReference(AgentHostModel):
    runtime_binding_id: str = Field(min_length=1)
    remote_session_id: str = Field(min_length=1)


class AgentSessionRecord(AgentHostModel):
    session_id: UUID = Field(default_factory=uuid4)
    target_id: str = Field(min_length=1)
    runtime_session: RuntimeSessionReference
    title: str | None = None
    created_at: AwareDatetime


class CreateAgentSessionCommand(AgentHostModel):
    title: str | None = None


class StartSessionRunCommand(AgentHostModel):
    run_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    input_text: str = Field(min_length=1, pattern=r"\S")


class HistoryPageQuery(AgentHostModel):
    limit: int = Field(default=100, ge=1, le=500)
    offset: NonNegativeInt = 0
    order: Literal["oldest", "latest"] = "latest"


class HistoryText(AgentHostModel):
    kind: Literal["text"] = "text"
    text: str


class HistoryUnsupportedContent(AgentHostModel):
    kind: Literal["unsupported"] = "unsupported"
    content_type: str = Field(min_length=1)


class HistoryToolCall(AgentHostModel):
    kind: Literal["tool_call"] = "tool_call"
    tool_call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, JsonValue]


HistoryContent = Annotated[
    HistoryText | HistoryToolCall | HistoryUnsupportedContent,
    Field(discriminator="kind"),
]


class AgentHistoryMessage(AgentHostModel):
    message_id: str = Field(min_length=1)
    role: Literal["system", "developer", "user", "assistant", "tool", "unsupported"]
    content: tuple[HistoryContent, ...]
    tool_call_id: str | None = None
    tool_name: str | None = None
    created_at: AwareDatetime | None = None


class AgentHistoryPage(AgentHostModel):
    session_id: UUID
    messages: tuple[AgentHistoryMessage, ...]
    query: HistoryPageQuery
    has_more: bool | None = None


class RuntimeAgentSession(AgentHostModel):
    remote_session_id: str = Field(min_length=1)
    title: str | None = None


class RuntimeHistoryPage(AgentHostModel):
    remote_session_id: str = Field(min_length=1)
    messages: tuple[AgentHistoryMessage, ...]
    query: HistoryPageQuery
    has_more: bool | None = None


class RuntimeRunHandle(AgentHostModel):
    runtime_binding_id: str = Field(min_length=1)
    remote_run_id: str = Field(min_length=1)


class RuntimeSessionRunStarted(AgentHostModel):
    kind: Literal["session_adapter.started"] = "session_adapter.started"
    handle: RuntimeRunHandle


class RuntimeSessionTextDelta(AgentHostModel):
    kind: Literal["session_adapter.text.delta"] = "session_adapter.text.delta"
    delta: str


class RuntimeSessionRunCompleted(AgentHostModel):
    kind: Literal["session_adapter.completed"] = "session_adapter.completed"
    remote_session_id: str = Field(min_length=1)
    output_text: str
    usage: TokenUsage = Field(default_factory=TokenUsage)


class RuntimeSessionRunCancelled(AgentHostModel):
    kind: Literal["session_adapter.cancelled"] = "session_adapter.cancelled"


RuntimeSessionRunEvent = Annotated[
    RuntimeSessionRunStarted
    | RuntimeSessionTextDelta
    | RuntimeSessionRunCompleted
    | RuntimeSessionRunCancelled,
    Field(discriminator="kind"),
]


class RuntimeStopReceipt(AgentHostModel):
    handle: RuntimeRunHandle
    accepted: bool


class RuntimeRunState(AgentHostModel):
    handle: RuntimeRunHandle
    state: Literal["queued", "running", "stopping", "completed", "failed", "cancelled", "unknown"]

    @property
    def is_terminal(self) -> bool:
        return self.state in {"completed", "failed", "cancelled"}
