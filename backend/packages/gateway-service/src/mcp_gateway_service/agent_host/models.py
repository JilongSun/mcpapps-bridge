"""Provider-neutral Agent Host commands and results."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, PositiveInt

AgentFinishReason = Literal["stop", "length", "tool_calls", "content_filter", "function_call"]


class AgentRuntimeInterface(StrEnum):
    OPENAI_CHAT_COMPLETIONS = "openai-chat-completions"
    OPENAI_RESPONSES = "openai-responses"
    HERMES_RUNS = "hermes-runs"


class AgentCapability(StrEnum):
    TEXT_GENERATION = "text-generation"
    TOKEN_USAGE = "token-usage"
    STREAMING_TEXT = "streaming-text"
    SESSION_CONTINUITY = "session-continuity"
    TOOL_ACTIVITY = "tool-activity"
    APPROVALS = "approvals"
    RUN_STOP = "run-stop"
    RUN_STEER = "run-steer"
    DETACHED_RUNS = "detached-runs"


class AgentHostModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AgentModel(AgentHostModel):
    model_id: str = Field(min_length=1)
    created_at: datetime | None = None
    owned_by: str = "unknown"


class AgentEndpointAssignment(AgentHostModel):
    endpoint_slug: str = Field(pattern=r"^[a-z][a-z0-9-]*$")


class AgentRuntimeProfile(AgentHostModel):
    integration_kind: str = Field(min_length=1)
    interface: AgentRuntimeInterface
    capabilities: frozenset[AgentCapability] = Field(default_factory=frozenset)


class AgentTarget(AgentHostModel):
    target_id: str = Field(min_length=1)
    runtime_profile: AgentRuntimeProfile
    endpoint_assignment: AgentEndpointAssignment


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
