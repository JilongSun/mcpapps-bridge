"""Framework- and persistence-independent MCP bridge contracts."""

from .observations import (
    BindingAvailabilityChanged,
    BridgeErrorRaised,
    BridgeFailure,
    BridgeFailureCode,
    BridgeObservation,
    BridgeSessionStarted,
    ResourceLoaded,
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
    AppResource,
    ResourceDescriptor,
    ToolCallResult,
    ToolDescriptor,
    UpstreamIdentity,
)

__all__ = [
    "AppResource",
    "BindingAvailabilityChanged",
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
    "NoOpBridgeObserver",
    "ResourceDescriptor",
    "ResourceLoaded",
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
