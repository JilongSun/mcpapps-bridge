"""Server composition adapters for managed MCP sessions."""

from .builder import assemble_gateway_session_coordinator, to_domain_connection

__all__ = [
    "assemble_gateway_session_coordinator",
    "to_domain_connection",
]
