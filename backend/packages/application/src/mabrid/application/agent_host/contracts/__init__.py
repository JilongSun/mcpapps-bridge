"""Provider-neutral contracts owned by the Agent Host application."""

from .adapter_events import AgentAdapterCompleted, AgentAdapterEvent, AgentAdapterTextDelta
from .base import AgentHostModel
from .profile import AgentCapability, AgentRuntimeInterface, AgentRuntimeProfile
from .run import (
    AgentFinishReason,
    AgentMessage,
    AgentRunResult,
    GenerationOptions,
    StartRunCommand,
    TokenUsage,
)
from .run_events import (
    AgentRunCompleted,
    AgentRunEvent,
    AgentRunFailed,
    AgentRunStarted,
    AssistantTextCompleted,
    AssistantTextDelta,
)
from .target import AgentEndpointAssignment, AgentModel, AgentTarget

__all__ = [
    "AgentAdapterCompleted",
    "AgentAdapterEvent",
    "AgentAdapterTextDelta",
    "AgentCapability",
    "AgentEndpointAssignment",
    "AgentFinishReason",
    "AgentHostModel",
    "AgentMessage",
    "AgentModel",
    "AgentRunCompleted",
    "AgentRunEvent",
    "AgentRunFailed",
    "AgentRunResult",
    "AgentRunStarted",
    "AgentRuntimeInterface",
    "AgentRuntimeProfile",
    "AgentTarget",
    "AssistantTextCompleted",
    "AssistantTextDelta",
    "GenerationOptions",
    "StartRunCommand",
    "TokenUsage",
]
