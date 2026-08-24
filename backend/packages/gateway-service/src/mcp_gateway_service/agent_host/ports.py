"""Provider ports used by the Agent Host application context."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from .events import AgentAdapterEvent
from .models import AgentModel, StartRunCommand


class AgentRuntimeAdapter(Protocol):
    async def list_models(self) -> list[AgentModel]: ...

    def run(self, command: StartRunCommand) -> AsyncIterator[AgentAdapterEvent]: ...
