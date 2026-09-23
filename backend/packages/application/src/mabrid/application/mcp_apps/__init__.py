"""Public facade for the MCP Apps application context."""

from .contracts import (
    ApplicationResourceContent,
    McpAppsModel,
    WidgetCreated,
    WidgetEvent,
    WidgetFailed,
    WidgetInstance,
    WidgetToolResult,
)
from .observers import McpAppsLifecycleObserverFactory
from .ports import OperationAttributionReader, WidgetEventStore
from .projector import McpAppsLifecycleProjector
from .store import InMemoryWidgetEventStore

__all__ = [
    "ApplicationResourceContent",
    "InMemoryWidgetEventStore",
    "McpAppsLifecycleObserverFactory",
    "McpAppsLifecycleProjector",
    "McpAppsModel",
    "OperationAttributionReader",
    "WidgetCreated",
    "WidgetEvent",
    "WidgetEventStore",
    "WidgetFailed",
    "WidgetInstance",
    "WidgetToolResult",
]
