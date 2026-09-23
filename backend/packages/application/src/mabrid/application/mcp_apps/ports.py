"""Ports required by the MCP Apps lifecycle application."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from ..agent_host import OperationRunAttribution
from .contracts import WidgetEvent


class OperationAttributionReader(Protocol):
    async def get(
        self,
        session_key: str,
        operation_key: str,
    ) -> OperationRunAttribution | None: ...


class WidgetEventStore(Protocol):
    async def append(self, event: WidgetEvent) -> None: ...

    async def list_for_run(self, run_id: UUID) -> tuple[WidgetEvent, ...]: ...
