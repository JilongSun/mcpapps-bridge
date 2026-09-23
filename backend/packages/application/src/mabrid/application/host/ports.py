"""Source ports used by Host presentation composition."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Protocol
from uuid import UUID

from ..agent_host import AgentRunEvent, StartRunCommand
from ..mcp_apps import WidgetEvent


class AgentRunEventSource(Protocol):
    def run_events(self, command: StartRunCommand) -> AsyncGenerator[AgentRunEvent, None]: ...


class WidgetEventReader(Protocol):
    async def list_for_run(self, run_id: UUID) -> tuple[WidgetEvent, ...]: ...

    async def wait_until_settled(self, run_id: UUID) -> None: ...
