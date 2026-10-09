"""Public facade for Host presentation composition."""

from .contracts import (
    HostAgentEvent,
    HostEvent,
    HostEventBase,
    HostEventModel,
    HostWidgetEvent,
    HostToolEvent,
)
from .ports import AgentRunEventSource, WidgetEventReader, ToolActivityReader, SessionRunEventSource
from .service import HostEventStream, HostSessionEventStream
from .composition import (
    HostCapabilityComposition,
    McpAppsComposition,
    NativeSessionPorts,
    compose_host_capabilities,
    compose_mcp_apps,
)
from .settlement import HostRunSettlement, HostObservationFactory

__all__ = [
    "HostSessionEventStream",
    "SessionRunEventSource",
    "HostToolEvent",
    "ToolActivityReader",
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
