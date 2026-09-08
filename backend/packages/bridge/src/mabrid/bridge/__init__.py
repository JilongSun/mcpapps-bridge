"""Stable embedding facade for the framework- and persistence-independent MCP bridge.

The root exposes protocol contracts, engine lifecycle, the raw ASGI entry point, and injection
ports. Concrete routers, SDK hosts, runtimes, and transport clients remain in owning subpackages.
"""

from .downstream import (
    McpSessionBroker,
    McpTransportSession,
    create_mcp_asgi_app,
)
from .engine import BridgeEngine, BridgeSession
from .contracts import (
    BindingPlan,
    BindingAvailabilityStatus,
    BindingAvailabilityChanged,
    BridgeCapabilities,
    BridgeErrorRaised,
    BridgeFailure,
    BridgeFailureCode,
    BridgeObservation,
    BridgeSessionStarted,
    ResourceRead,
    ReadResourceResult,
    ResourceContent,
    ResourceDescriptor,
    EndpointMode,
    EndpointPlan,
    NoOpBridgeObserver,
    BridgeObserver,
    SseUpstreamConfig,
    StdioUpstreamConfig,
    StreamableHttpUpstreamConfig,
    ToolCallCompleted,
    ToolCallResult,
    ToolCallStarted,
    ToolDescriptor,
    ToolsPublished,
    UpstreamConfig,
    UpstreamIdentity,
)
from .upstream import (
    UpstreamClient,
    UpstreamClientFactory,
)

__all__ = [
    "BindingAvailabilityChanged",
    "BindingAvailabilityStatus",
    "BindingPlan",
    "BridgeCapabilities",
    "BridgeEngine",
    "BridgeErrorRaised",
    "BridgeFailure",
    "BridgeFailureCode",
    "BridgeObservation",
    "BridgeObserver",
    "BridgeSessionStarted",
    "BridgeSession",
    "EndpointMode",
    "EndpointPlan",
    "NoOpBridgeObserver",
    "McpSessionBroker",
    "McpTransportSession",
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
    "UpstreamClient",
    "UpstreamClientFactory",
    "UpstreamIdentity",
    "create_mcp_asgi_app",
]
