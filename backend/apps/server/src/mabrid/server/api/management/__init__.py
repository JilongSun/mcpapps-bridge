"""Read-only management HTTP adapters."""

from .agent_host import create_agent_host_management_router
from .gateway import create_gateway_management_router

__all__ = ["create_agent_host_management_router", "create_gateway_management_router"]
