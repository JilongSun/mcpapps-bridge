"""Framework- and persistence-independent MCP bridge contracts."""

from .downstream import BridgeDownstreamServer
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
from .upstream import (
    DefaultUpstreamClientFactory,
    SseUpstreamClient,
    StdioUpstreamClient,
    StreamableHttpUpstreamClient,
    UpstreamClientFactory,
    build_upstream_client,
)

__all__ = [
    "AppResource",
    "AggregateRouter",
    "BindingAvailabilityChanged",
    "BindingAvailabilityStatus",
    "BindingPlan",
    "BridgeCapabilities",
    "BridgeDownstreamServer",
    "BridgeErrorRaised",
    "BridgeFailure",
    "BridgeFailureCode",
    "BridgeObservation",
    "BridgeObserver",
    "BridgeSessionStarted",
    "DefaultUpstreamClientFactory",
    "EndpointMode",
    "EndpointPlan",
    "NoOpBridgeObserver",
    "McpSessionRouter",
    "PassthroughRouter",
    "ResourceDescriptor",
    "ResourceLoaded",
    "SseUpstreamConfig",
    "SseUpstreamClient",
    "StdioUpstreamConfig",
    "StdioUpstreamClient",
    "StreamableHttpUpstreamConfig",
    "StreamableHttpUpstreamClient",
    "ToolCallCompleted",
    "ToolCallResult",
    "ToolCallStarted",
    "ToolDescriptor",
    "ToolsPublished",
    "UpstreamConfig",
    "UpstreamClient",
    "UpstreamClientFactory",
    "UpstreamIdentity",
    "UpstreamRuntime",
    "build_upstream_client",
]
