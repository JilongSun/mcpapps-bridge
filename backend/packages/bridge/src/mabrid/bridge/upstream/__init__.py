"""Upstream MCP transport adapters and same-task session runtime.

Connectors translate MCP SDK client values into bridge contracts. The runtime serializes one
stateful upstream session through a persistent owner task so SDK cancel scopes are entered, used,
and exited by the same task.
"""

from .factory import (
    DefaultUpstreamClientFactory,
    UpstreamClientFactory,
    build_upstream_client,
)
from .runtime import UpstreamClient, UpstreamRuntime
from .sse import SseUpstreamClient
from .stdio import StdioUpstreamClient
from .streamable_http import StreamableHttpUpstreamClient

__all__ = [
    "DefaultUpstreamClientFactory",
    "SseUpstreamClient",
    "StdioUpstreamClient",
    "StreamableHttpUpstreamClient",
    "UpstreamClient",
    "UpstreamClientFactory",
    "UpstreamRuntime",
    "build_upstream_client",
]
