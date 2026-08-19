"""Framework- and persistence-independent MCP bridge contracts."""

from .observations import (
    BindingAvailabilityStatus,
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
from .runtime import UpstreamClient, UpstreamRuntime
from .router import AggregateRouter, McpSessionRouter, PassthroughRouter

__all__ = [
    "AppResource",
    "AggregateRouter",
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
    "NoOpBridgeObserver",
    "McpSessionRouter",
    "PassthroughRouter",
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
    "UpstreamClient",
    "UpstreamIdentity",
    "UpstreamRuntime",
]
