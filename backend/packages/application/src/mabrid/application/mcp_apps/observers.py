"""Construct MCP Apps lifecycle projectors for assigned Gateway sessions."""

from __future__ import annotations

from mabrid.bridge import BridgeObserver

from .ports import OperationAttributionReader, WidgetEventStore
from .projector import McpAppsLifecycleProjector


class McpAppsLifecycleObserverFactory:
    def __init__(
        self,
        endpoint_slug: str,
        attributions: OperationAttributionReader,
        events: WidgetEventStore,
    ) -> None:
        self._endpoint_slug = endpoint_slug
        self._attributions = attributions
        self._events = events

    def create(self, session_key: str, endpoint_slug: str) -> BridgeObserver | None:
        if endpoint_slug != self._endpoint_slug:
            return None
        return McpAppsLifecycleProjector(session_key, self._attributions, self._events)
