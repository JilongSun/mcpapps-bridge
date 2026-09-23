"""Compose the optional first-party MCP Apps Host workflow."""

from __future__ import annotations

from dataclasses import dataclass

from mabrid.application.agent_host import OperationRunAttributionRegistry
from mabrid.application.mcp_apps import (
    InMemoryWidgetEventStore,
    McpAppsLifecycleObserverFactory,
)


@dataclass(frozen=True)
class McpAppsComposition:
    events: InMemoryWidgetEventStore
    bridge_observer_factory: McpAppsLifecycleObserverFactory


def compose_mcp_apps(
    endpoint_slug: str,
    operation_attributions: OperationRunAttributionRegistry,
) -> McpAppsComposition:
    events = InMemoryWidgetEventStore()
    return McpAppsComposition(
        events=events,
        bridge_observer_factory=McpAppsLifecycleObserverFactory(
            endpoint_slug,
            operation_attributions,
            events,
        ),
    )
