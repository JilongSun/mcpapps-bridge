"""Session-scoped MCP routing and public identity transformation.

Routing consumes immutable endpoint plans, owns passthrough or aggregate public names and URI
maps, and emits core observations. It does not own SDK transports, persistence, or endpoint
publication policy.
"""

from .aggregate import AggregateRouter
from .passthrough import PassthroughRouter
from .ports import McpSessionRouter

__all__ = ["AggregateRouter", "McpSessionRouter", "PassthroughRouter"]
