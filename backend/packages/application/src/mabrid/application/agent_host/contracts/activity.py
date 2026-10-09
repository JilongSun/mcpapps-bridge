"""Run-owned tool invocation activity without Gateway routing identifiers."""

from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import Field

from .base import AgentHostModel


class ToolInvocationResult(AgentHostModel):
    content: tuple[dict[str, Any], ...] = ()
    structured_content: dict[str, Any] | None = None
    is_error: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolInvocationEventBase(AgentHostModel):
    event_id: UUID = Field(default_factory=uuid4)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    run_id: UUID
    target_id: str = Field(min_length=1)
    tool_invocation_id: UUID
    tool_name: str = Field(min_length=1)


class ToolInvocationStarted(ToolInvocationEventBase):
    kind: Literal["tool.started"] = "tool.started"
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolInvocationCompleted(ToolInvocationEventBase):
    kind: Literal["tool.completed"] = "tool.completed"
    result: ToolInvocationResult


class ToolInvocationFailed(ToolInvocationEventBase):
    kind: Literal["tool.failed"] = "tool.failed"
    error_code: str = Field(min_length=1)
    error_message: str = Field(min_length=1)
    result: ToolInvocationResult | None = None


ToolActivityEvent = Annotated[
    ToolInvocationStarted | ToolInvocationCompleted | ToolInvocationFailed,
    Field(discriminator="kind"),
]
