"""MCP proxy, transport, and resource handling modules."""

from .builder import build_bridge_manager
from .downstream import BridgeDownstreamServer
from .manager import BridgeManager, PassthroughSessionRuntime, PublishedEndpoint
from .runtime import UpstreamRuntime
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
    "BridgeManager",
    "BridgeDownstreamServer",
    "PassthroughSessionRuntime",
    "PublishedEndpoint",
    "UpstreamRuntime",
    "UpstreamServerConfig",
    "build_upstream_client",
    "SseUpstreamMcpClient",
    "StdioUpstreamMcpClient",
    "StreamableHttpUpstreamMcpClient",
    "DefaultUpstreamMcpClientFactory",
    "UpstreamMcpClient",
    "UpstreamMcpClientFactory",
    "build_bridge_manager",
]
