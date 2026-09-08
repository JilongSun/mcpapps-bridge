"""Stable project-owned contracts shared across bridge-core components.

Contracts contain protocol values and behavior boundaries only. They do not import MCP SDK
servers, Starlette transports, application services, persistence, or deployment infrastructure.
"""

from .methods import McpMethodRouter
from .observations import (
    BindingAvailabilityChanged,
    BindingAvailabilityStatus,
    BridgeErrorRaised,
    BridgeFailure,
    BridgeFailureCode,
    BridgeObservation,
    BridgeSessionStarted,
    ResourceRead,
    ToolCallCompleted,
    ToolCallStarted,
    ToolsPublished,
)
from .observer import BridgeObserver, NoOpBridgeObserver
from .plans import (
    BindingPlan,
    BridgeCapabilities,
    EndpointMode,
    EndpointPlan,
    SseUpstreamConfig,
    StdioUpstreamConfig,
    StreamableHttpUpstreamConfig,
    UpstreamConfig,
)
from .protocol import (
    ReadResourceResult,
    ResourceContent,
    ResourceDescriptor,
    ToolCallResult,
    ToolDescriptor,
    UpstreamIdentity,
)

__all__ = [
    "BindingAvailabilityChanged",
    "BindingAvailabilityStatus",
    "BindingPlan",
    "BridgeCapabilities",
    "BridgeErrorRaised",
    "BridgeFailure",
    "BridgeFailureCode",
    "BridgeObservation",
    "BridgeObserver",
    "BridgeSessionStarted",
    "EndpointMode",
    "EndpointPlan",
    "McpMethodRouter",
    "NoOpBridgeObserver",
    "ReadResourceResult",
    "ResourceContent",
    "ResourceDescriptor",
    "ResourceRead",
    "SseUpstreamConfig",
    "StdioUpstreamConfig",
    "StreamableHttpUpstreamConfig",
    "ToolCallCompleted",
    "ToolCallResult",
    "ToolCallStarted",
    "ToolDescriptor",
    "ToolsPublished",
    "UpstreamConfig",
    "UpstreamIdentity",
]
