"""Provider ports used by the Agent Host application context."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from .events import AgentAdapterEvent
from .models import AgentRuntimeProfile, StartRunCommand


class AgentRuntime(Protocol):
    @property
    def profile(self) -> AgentRuntimeProfile: ...

    def run(self, command: StartRunCommand) -> AsyncIterator[AgentAdapterEvent]: ...


class ManagedAgentRuntime(AgentRuntime, Protocol):
    async def close(self) -> None: ...
