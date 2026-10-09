"""Agent Session use cases with durable binding and conservative Run settlement."""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from uuid import UUID

import anyio

from ..contracts.session import (
    AgentHistoryPage,
    AgentSessionRecord,
    AgentSessionRunStatus,
    CreateAgentSessionCommand,
    HistoryPageQuery,
    RuntimeSessionReference,
    RuntimeSessionRunCompleted,
    RuntimeSessionRunEvent,
    RuntimeSessionRunStarted,
    RuntimeSessionRunCancelled,
    UnsettledSessionRun,
    RuntimeStopReceipt,
    StartSessionRunCommand,
)
from .coordination import AgentRunCoordinator
from .ports import (
    AgentSessionRepository,
    RuntimeSessionCatalog,
    RuntimeSessionExecution,
    RuntimeSessionHistory,
    RuntimeSessionRunControl,
    AgentRunSettlement,
)
from .session_errors import AgentSessionError


async def restore_target_run_ownership(
    repository: AgentSessionRepository,
    coordinator: AgentRunCoordinator,
    target_id: str,
) -> None:
    pending = await repository.get_unsettled_run(target_id)
    if pending is None:
        return
    active = await coordinator.active_run_id(target_id)
    if active is None:
        await coordinator.start_run(target_id, pending.run_id)
    elif active != pending.run_id:
        raise AgentSessionError(
            "run_state_unknown", "Target ownership differs from its durable Run"
        )


class AgentSessionService:
    def __init__(
        self,
        *,
        target_id: str,
        runtime_binding_id: str,
        repository: AgentSessionRepository,
        catalog: RuntimeSessionCatalog,
        history: RuntimeSessionHistory,
        execution: RuntimeSessionExecution,
        control: RuntimeSessionRunControl,
        coordinator: AgentRunCoordinator,
        settlement: AgentRunSettlement | None = None,
    ) -> None:
        self.target_id = target_id
        self.runtime_binding_id = runtime_binding_id
        self._repository = repository
        self._catalog = catalog
        self._history = history
        self._execution = execution
        self._control = control
        self.coordinator = coordinator
        self._settlement = settlement
        self._open_runs: set[UUID] = set()
        self._stop_requested: set[UUID] = set()
        self._terminal_observed: set[UUID] = set()

    async def create_session(self, command: CreateAgentSessionCommand) -> AgentSessionRecord:
        remote = await self._catalog.create_session(command)
        session = AgentSessionRecord(
            target_id=self.target_id,
            runtime_session=RuntimeSessionReference(
                runtime_binding_id=self.runtime_binding_id,
                remote_session_id=remote.remote_session_id,
            ),
            title=remote.title,
            created_at=datetime.now(timezone.utc),
        )
        await self._repository.add(session)
        return session

    async def list_sessions(
        self, *, limit: int = 20, offset: int = 0
    ) -> tuple[AgentSessionRecord, ...]:
        return await self._repository.list_sessions(
            target_id=self.target_id, limit=limit, offset=offset
        )

    async def get_target_run(self) -> AgentSessionRunStatus | None:
        pending = await self._repository.get_unsettled_run(self.target_id)
        if pending is None:
            return None
        return AgentSessionRunStatus(
            session_id=pending.session_id,
            run_id=pending.run_id,
            state="active" if pending.run_id in self._open_runs else "unsettled",
        )

    async def _load(self, session_id: UUID) -> AgentSessionRecord:
        session = await self._repository.get(session_id)
        if session is None or session.target_id != self.target_id:
            raise AgentSessionError("session_not_found", "Agent Session was not found")
        if session.runtime_session.runtime_binding_id != self.runtime_binding_id:
            raise AgentSessionError(
                "runtime_binding_changed", "Agent Session belongs to another runtime deployment"
            )
        return session

    async def reopen_session(self, session_id: UUID) -> AgentSessionRecord:
        session = await self._load(session_id)
        remote = await self._catalog.get_session(session.runtime_session)
        return session.model_copy(update={"title": remote.title})

    async def read_history(self, session_id: UUID, query: HistoryPageQuery) -> AgentHistoryPage:
        session = await self._load(session_id)
        page = await self._history.read_history(session.runtime_session, query)
        await self._adopt_reference(session, page.remote_session_id)
        return AgentHistoryPage(
            session_id=session_id, messages=page.messages, query=page.query, has_more=page.has_more
        )

    async def _adopt_reference(self, session: AgentSessionRecord, remote_session_id: str) -> None:
        expected = session.runtime_session
        if expected.remote_session_id == remote_session_id:
            return
        replacement = RuntimeSessionReference(
            runtime_binding_id=self.runtime_binding_id, remote_session_id=remote_session_id
        )
        await self._catalog.get_session(replacement)
        if await self._repository.update_runtime_session(
            session.session_id, expected=expected, replacement=replacement
        ):
            return
        current = await self._load(session.session_id)
        if current.runtime_session != replacement:
            raise AgentSessionError(
                "runtime_binding_changed", "Session reference changed during runtime execution"
            )

    async def run_session(
        self, command: StartSessionRunCommand
    ) -> AsyncGenerator[RuntimeSessionRunEvent, None]:
        session = await self._load(command.session_id)
        pending = await self._repository.get_unsettled_run(self.target_id)
        if pending is not None:
            raise AgentSessionError(
                "target_busy" if pending.run_id in self._open_runs else "run_state_unknown",
                "Target has an unsettled Run; reconcile it before invoking again",
            )
        await self.coordinator.start_run(self.target_id, command.run_id)
        claimed = False
        try:
            claimed = await self._repository.claim_run(session, command.run_id)
            if not claimed:
                raise AgentSessionError(
                    "run_state_unknown", "Target already has durable execution ownership"
                )
        finally:
            if not claimed:
                with anyio.CancelScope(shield=True):
                    await self.coordinator.finish_run(self.target_id, command.run_id)
        stream = self._execution.run_session(session.runtime_session, command)
        self._open_runs.add(command.run_id)
        closed = False
        unresolved = False
        try:
            try:
                async for event in stream:
                    if isinstance(event, RuntimeSessionRunStarted):
                        await self._repository.record_runtime_run(
                            self.target_id, command.run_id, event.handle
                        )
                    elif isinstance(event, RuntimeSessionRunCompleted):
                        self._terminal_observed.add(command.run_id)
                        cancelled = command.run_id in self._stop_requested
                        if self._settlement is not None:
                            await self._settlement.wait_until_settled(command.run_id)
                        await self._adopt_reference(session, event.remote_session_id)
                        if cancelled:
                            yield RuntimeSessionRunCancelled()
                            continue
                    yield event
            finally:
                with anyio.CancelScope(shield=True):
                    await stream.aclose()
                closed = True
                if self._settlement is not None:
                    with anyio.CancelScope(shield=True):
                        await self._settlement.wait_until_settled(command.run_id)
        except AgentSessionError as exc:
            unresolved = exc.code == "run_state_unknown"
            raise
        finally:
            self._open_runs.discard(command.run_id)
            self._stop_requested.discard(command.run_id)
            self._terminal_observed.discard(command.run_id)
            if closed and not unresolved:
                with anyio.CancelScope(shield=True):
                    await self._repository.release_run(self.target_id, command.run_id)
                    await self.coordinator.finish_run(self.target_id, command.run_id)

    async def _validate_run_reference(
        self, pending: UnsettledSessionRun | None, session_id: UUID | None, run_id: UUID | None
    ) -> None:
        if session_id is not None:
            await self._load(session_id)
        if (session_id is not None or run_id is not None) and (
            pending is None
            or (session_id is not None and pending.session_id != session_id)
            or (run_id is not None and pending.run_id != run_id)
        ):
            raise AgentSessionError("run_not_found", "Run was not found for this Session")

    async def request_stop(
        self, run_id: UUID, *, session_id: UUID | None = None
    ) -> RuntimeStopReceipt:
        pending = await self._repository.get_unsettled_run(self.target_id)
        if session_id is not None:
            await self._validate_run_reference(pending, session_id, run_id)
        if pending is None or pending.run_id != run_id or pending.handle is None:
            raise AgentSessionError("run_state_unknown", "No controllable remote Run is known")
        if run_id in self._terminal_observed:
            return RuntimeStopReceipt(handle=pending.handle, accepted=False)
        receipt = await self._control.request_stop(pending.handle)
        if receipt.accepted and run_id in self._open_runs and run_id not in self._terminal_observed:
            self._stop_requested.add(run_id)
        return receipt

    async def reconcile_run(
        self, *, session_id: UUID | None = None, run_id: UUID | None = None
    ) -> bool:
        pending = await self._repository.get_unsettled_run(self.target_id)
        await self._validate_run_reference(pending, session_id, run_id)
        if pending is None:
            return True
        if pending.run_id in self._open_runs:
            return False
        active = await self.coordinator.active_run_id(self.target_id)
        if active is None:
            await self.coordinator.start_run(self.target_id, pending.run_id)
        elif active != pending.run_id:
            raise AgentSessionError(
                "run_state_unknown", "Target ownership differs from its durable Run"
            )
        if pending.runtime_binding_id != self.runtime_binding_id:
            raise AgentSessionError(
                "runtime_binding_changed", "Unsettled Run belongs to another runtime deployment"
            )
        if pending.handle is None:
            return False
        state = await self._control.get_run_state(pending.handle)
        if not state.is_terminal:
            return False
        if self._settlement is not None:
            try:
                await self._settlement.wait_until_settled(pending.run_id)
            except AgentSessionError as exc:
                if exc.code != "runtime_contract_error":
                    raise
        await self._repository.release_run(self.target_id, pending.run_id)
        await self.coordinator.finish_run(self.target_id, pending.run_id)
        return True

    async def restore_ownership(self) -> None:
        await restore_target_run_ownership(self._repository, self.coordinator, self.target_id)
