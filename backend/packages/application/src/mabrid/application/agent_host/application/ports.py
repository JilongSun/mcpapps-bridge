"""Outbound ports owned by the Agent Host application."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Protocol
from uuid import UUID

from ..contracts import AgentAdapterEvent, AgentRuntimeProfile, StartRunCommand
from ..contracts.session import (
    AgentSessionRecord,
    CreateAgentSessionCommand,
    HistoryPageQuery,
    RuntimeAgentSession,
    RuntimeHistoryPage,
    RuntimeRunHandle,
    RuntimeRunState,
    RuntimeSessionReference,
    RuntimeSessionRunEvent,
    RuntimeStopReceipt,
    StartSessionRunCommand,
    UnsettledSessionRun,
)


class AgentRuntime(Protocol):
    @property
    def profile(self) -> AgentRuntimeProfile: ...

    def run(self, command: StartRunCommand) -> AsyncGenerator[AgentAdapterEvent, None]: ...


class ManagedAgentRuntime(AgentRuntime, Protocol):
    async def close(self) -> None: ...


class AgentRunSettlement(Protocol):
    async def wait_until_settled(self, run_id: UUID) -> None: ...


class AgentSessionRepository(Protocol):
    async def add(self, session: AgentSessionRecord) -> None: ...

    async def get(self, session_id: UUID) -> AgentSessionRecord | None: ...

    async def list_sessions(
        self, *, target_id: str, limit: int, offset: int
    ) -> tuple[AgentSessionRecord, ...]: ...

    async def update_runtime_session(
        self,
        session_id: UUID,
        *,
        expected: RuntimeSessionReference,
        replacement: RuntimeSessionReference,
    ) -> bool: ...

    async def get_unsettled_run(self, target_id: str) -> UnsettledSessionRun | None: ...

    async def claim_run(self, session: AgentSessionRecord, run_id: UUID) -> bool: ...

    async def record_runtime_run(
        self, target_id: str, run_id: UUID, handle: RuntimeRunHandle
    ) -> None: ...

    async def release_run(self, target_id: str, run_id: UUID) -> None: ...


class RuntimeSessionCatalog(Protocol):
    async def create_session(self, command: CreateAgentSessionCommand) -> RuntimeAgentSession: ...

    async def get_session(self, reference: RuntimeSessionReference) -> RuntimeAgentSession: ...


class RuntimeSessionHistory(Protocol):
    async def read_history(
        self, reference: RuntimeSessionReference, query: HistoryPageQuery
    ) -> RuntimeHistoryPage: ...


class RuntimeSessionExecution(Protocol):
    def run_session(
        self, reference: RuntimeSessionReference, command: StartSessionRunCommand
    ) -> AsyncGenerator[RuntimeSessionRunEvent, None]: ...


class RuntimeSessionRunControl(Protocol):
    async def request_stop(self, handle: RuntimeRunHandle) -> RuntimeStopReceipt: ...

    async def get_run_state(self, handle: RuntimeRunHandle) -> RuntimeRunState: ...
