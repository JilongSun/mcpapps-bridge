"""Public bridge engine and hosted session lifecycle.

The engine composes routing, upstream owner tasks, downstream MCP hosting, and structured cleanup
from immutable plans. It remains independent of managed topology, persistence, and deployment
lifespan.
"""

from .lifecycle import BridgeEngine, BridgeSession

__all__ = ["BridgeEngine", "BridgeSession"]
