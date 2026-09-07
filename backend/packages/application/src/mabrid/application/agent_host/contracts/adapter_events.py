"""Events emitted through the outbound Agent Runtime port."""

from typing import Annotated, Literal, TypeAlias

from pydantic import Field

from .base import AgentHostModel
from .run import AgentFinishReason, TokenUsage


class AgentAdapterTextDelta(AgentHostModel):
    kind: Literal["adapter.text.delta"] = "adapter.text.delta"
    delta: str


class AgentAdapterCompleted(AgentHostModel):
    kind: Literal["adapter.completed"] = "adapter.completed"
    finish_reason: AgentFinishReason = "stop"
    usage: TokenUsage = Field(default_factory=TokenUsage)


AgentAdapterEvent: TypeAlias = Annotated[
    AgentAdapterTextDelta | AgentAdapterCompleted,
    Field(discriminator="kind"),
]
