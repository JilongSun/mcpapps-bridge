"""Public facade for Host presentation composition."""

from .contracts import HostAgentEvent, HostEvent, HostEventBase, HostEventModel, HostWidgetEvent
from .ports import AgentRunEventSource, WidgetEventReader
from .service import HostEventStream
from .composition import (
    HostCapabilityComposition,
    McpAppsComposition,
    NativeSessionPorts,
    compose_host_capabilities,
    compose_mcp_apps,
)
from .settlement import HostRunSettlement, HostObservationFactory

__all__ = [
    "HostCapabilityComposition",
    "McpAppsComposition",
    "NativeSessionPorts",
    "compose_host_capabilities",
    "compose_mcp_apps",
    "HostRunSettlement",
    "HostObservationFactory",
    "AgentRunEventSource",
    "HostAgentEvent",
    "HostEvent",
    "HostEventBase",
    "HostEventModel",
    "HostEventStream",
    "HostWidgetEvent",
    "WidgetEventReader",
]
