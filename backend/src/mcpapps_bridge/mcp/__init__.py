"""MCP proxy, transport, and resource handling modules."""

from mcp_bridge_core import AggregateRouter, McpSessionRouter, PassthroughRouter, UpstreamRuntime

from .builder import assemble_bridge_manager, to_domain_connection
from .downstream import BridgeDownstreamServer
from .manager import BridgeManager, BridgeSessionRuntime, PublishedEndpoint
from .upstream import (
    SseUpstreamMcpClient,
    StdioUpstreamMcpClient,
    StreamableHttpUpstreamMcpClient,
    DefaultUpstreamMcpClientFactory,
    UpstreamMcpClient,
    UpstreamMcpClientFactory,
    UpstreamServerConfig,
    build_upstream_client,
)

__all__ = [
    "AggregateRouter",
    "BridgeManager",
    "BridgeSessionRuntime",
    "BridgeDownstreamServer",
    "McpSessionRouter",
    "PassthroughRouter",
    "PublishedEndpoint",
    "UpstreamRuntime",
    "UpstreamServerConfig",
    "build_upstream_client",
    "assemble_bridge_manager",
    "SseUpstreamMcpClient",
    "StdioUpstreamMcpClient",
    "StreamableHttpUpstreamMcpClient",
    "DefaultUpstreamMcpClientFactory",
    "UpstreamMcpClient",
    "UpstreamMcpClientFactory",
    "to_domain_connection",
]
