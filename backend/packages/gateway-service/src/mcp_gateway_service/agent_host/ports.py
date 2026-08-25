"""Provider ports used by the Agent Host application context."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from .events import AgentAdapterEvent
from .models import StartRunCommand


class AgentRuntimeAdapter(Protocol):
    def run(self, command: StartRunCommand) -> AsyncIterator[AgentAdapterEvent]: ...
