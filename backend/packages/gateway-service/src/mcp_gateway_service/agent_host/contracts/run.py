"""Provider-neutral Agent Host run commands and terminal results."""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, NonNegativeInt, PositiveInt

from .base import AgentHostModel

AgentFinishReason = Literal["stop", "length", "tool_calls", "content_filter", "function_call"]


class AgentMessage(AgentHostModel):
    role: Literal["developer", "system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class GenerationOptions(AgentHostModel):
    temperature: float | None = None
    max_output_tokens: PositiveInt | None = None


class StartRunCommand(AgentHostModel):
    run_id: UUID = Field(default_factory=uuid4)
    model: str = Field(min_length=1)
    messages: tuple[AgentMessage, ...] = Field(min_length=1)
    options: GenerationOptions = Field(default_factory=GenerationOptions)


class TokenUsage(AgentHostModel):
    input_tokens: NonNegativeInt = 0
    output_tokens: NonNegativeInt = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class AgentRunResult(AgentHostModel):
    run_id: UUID
    model: str
    output_text: str
    finish_reason: AgentFinishReason = "stop"
    usage: TokenUsage = Field(default_factory=TokenUsage)
