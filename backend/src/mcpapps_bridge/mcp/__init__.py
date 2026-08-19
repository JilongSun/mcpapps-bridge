"""MCP proxy, transport, and resource handling modules."""

from mcp_bridge_core import (
    AggregateRouter,
    BridgeDownstreamServer,
    DefaultUpstreamClientFactory,
    McpSessionRouter,
    PassthroughRouter,
    SseUpstreamClient,
    StdioUpstreamClient,
    StreamableHttpUpstreamClient,
    UpstreamClient,
    UpstreamClientFactory,
    UpstreamRuntime,
    build_upstream_client,
)

from .builder import assemble_bridge_manager, to_domain_connection
from .manager import BridgeManager, BridgeSessionRuntime, PublishedEndpoint

__all__ = [
    "AggregateRouter",
    "BridgeManager",
    "BridgeSessionRuntime",
    "BridgeDownstreamServer",
    "McpSessionRouter",
    "PassthroughRouter",
    "PublishedEndpoint",
    "UpstreamRuntime",
    "build_upstream_client",
    "assemble_bridge_manager",
    "SseUpstreamClient",
    "StdioUpstreamClient",
    "StreamableHttpUpstreamClient",
    "DefaultUpstreamClientFactory",
    "UpstreamClient",
    "UpstreamClientFactory",
    "to_domain_connection",
]
