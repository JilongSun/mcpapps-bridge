"""Local runtime integration profile and implemented capabilities."""

from enum import StrEnum

from pydantic import Field

from .base import AgentHostModel


class AgentRuntimeInterface(StrEnum):
    OPENAI_CHAT_COMPLETIONS = "openai-chat-completions"


class AgentCapability(StrEnum):
    TEXT_GENERATION = "text-generation"
    TOKEN_USAGE = "token-usage"


class AgentRuntimeProfile(AgentHostModel):
    integration_kind: str = Field(min_length=1)
    interface: AgentRuntimeInterface
    capabilities: frozenset[AgentCapability] = Field(default_factory=frozenset)
