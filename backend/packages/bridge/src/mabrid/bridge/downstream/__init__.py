"""Downstream MCP adapters owned by bridge core.

This package translates project-owned bridge contracts into MCP SDK v1 method and transport
behavior. It may depend on Starlette ASGI types and the MCP SDK, but it never imports Mabrid
application services, persistence, FastAPI, or deployment configuration.
"""

from .asgi import McpSessionBroker, McpTransportSession, create_mcp_asgi_app
from .server import BridgeDownstreamServer

__all__ = [
    "BridgeDownstreamServer",
    "McpSessionBroker",
    "McpTransportSession",
    "create_mcp_asgi_app",
]
