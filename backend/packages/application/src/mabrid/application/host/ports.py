"""Source ports used by Host presentation composition."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Protocol
from uuid import UUID

from ..agent_host import (
    AgentRunEvent,
    StartRunCommand,
    ToolActivityEvent,
    StartSessionRunCommand,
    RuntimeSessionRunEvent,
)
from ..mcp_apps import WidgetEvent


class AgentRunEventSource(Protocol):
    def run_events(self, command: StartRunCommand) -> AsyncGenerator[AgentRunEvent, None]: ...


class SessionRunEventSource(Protocol):
    target_id: str

    def run_session(
        self, command: StartSessionRunCommand
    ) -> AsyncGenerator[RuntimeSessionRunEvent, None]: ...


class WidgetEventReader(Protocol):
    async def list_for_run(self, run_id: UUID) -> tuple[WidgetEvent, ...]: ...

    async def wait_for_events(self, run_id: UUID, after: int) -> tuple[WidgetEvent, ...]: ...

    async def wait_until_settled(self, run_id: UUID) -> None: ...


class ToolActivityReader(Protocol):
    async def list_for_run(self, run_id: UUID) -> tuple[ToolActivityEvent, ...]: ...

    async def wait_for_events(self, run_id: UUID, after: int) -> tuple[ToolActivityEvent, ...]: ...

    async def invocation_id(self, session_key: str, operation_key: str) -> UUID | None: ...
