"""Server-owned composition of application contexts and infrastructure adapters."""

from .agent_host import AgentHostComposition, AgentHostManagementView
from .bootstrap import BootstrapResult, bootstrap_server
from .gateway import GatewayComposition, GatewayManagementComposition
from mabrid.application.host import McpAppsComposition

__all__ = [
    "AgentHostComposition",
    "AgentHostManagementView",
    "BootstrapResult",
    "GatewayComposition",
    "GatewayManagementComposition",
    "McpAppsComposition",
    "bootstrap_server",
]
