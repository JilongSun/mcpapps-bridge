"""High-level entry points for the managed MCP Gateway application context.

Detailed topology, session, and inspection contracts are exposed by their owning subpackage
facades. This facade intentionally exports only the composed service and MCP transport broker.
"""

from .sessions import GatewayMcpSessionBroker, GatewaySessionCoordinator

__all__ = ["GatewayMcpSessionBroker", "GatewaySessionCoordinator"]
