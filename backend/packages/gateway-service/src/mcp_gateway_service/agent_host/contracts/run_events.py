"""Events emitted by Agent Host run orchestration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal, TypeAlias
from uuid import UUID, uuid4

from pydantic import Field, PositiveInt

from .base import AgentHostModel
from .run import AgentRunResult


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentRunEventBase(AgentHostModel):
    event_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    sequence: PositiveInt
    created_at: datetime = Field(default_factory=utc_now)


class AgentRunStarted(AgentRunEventBase):
    kind: Literal["run.started"] = "run.started"
    model: str


class AssistantTextDelta(AgentRunEventBase):
    kind: Literal["assistant.text.delta"] = "assistant.text.delta"
    delta: str


class AssistantTextCompleted(AgentRunEventBase):
    kind: Literal["assistant.text.completed"] = "assistant.text.completed"
    text: str


class AgentRunCompleted(AgentRunEventBase):
    kind: Literal["run.completed"] = "run.completed"
    result: AgentRunResult


class AgentRunFailed(AgentRunEventBase):
    kind: Literal["run.failed"] = "run.failed"
    error_message: str


AgentRunEvent: TypeAlias = Annotated[
    AgentRunStarted
    | AssistantTextDelta
    | AssistantTextCompleted
    | AgentRunCompleted
    | AgentRunFailed,
    Field(discriminator="kind"),
]
