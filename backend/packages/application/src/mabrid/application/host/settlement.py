"""Bounded Host observation and Run settlement without changing MCP results."""

from asyncio import Condition
from collections.abc import Iterable
from uuid import UUID

import anyio

from mabrid.bridge import BridgeObservation, BridgeObserver, ToolCallStarted, ToolCallCompleted

from ..agent_host import AgentRunCoordinator, AgentSessionError, OperationRunAttributionRegistry
from ..mcp_apps import WidgetEventStore
from ..gateway.sessions import BridgeSessionObserverFactory


class HostRunSettlement:
    def __init__(
        self, widgets: WidgetEventStore | None = None, *, timeout_seconds: float = 5.0
    ) -> None:
        self._widgets = widgets
        self._timeout = timeout_seconds
        self._condition = Condition()
        self._pending: dict[UUID, set[tuple[str, str]]] = {}
        self._failed: set[UUID] = set()

    async def start(self, run_id: UUID, session_key: str, operation_key: str) -> None:
        async with self._condition:
            self._pending.setdefault(run_id, set()).add((session_key, operation_key))

    async def complete(self, run_id: UUID, session_key: str, operation_key: str) -> None:
        async with self._condition:
            pending = self._pending.get(run_id)
            if pending is not None:
                pending.discard((session_key, operation_key))
                if not pending:
                    self._pending.pop(run_id)
            self._condition.notify_all()

    async def fail(self, run_id: UUID) -> None:
        async with self._condition:
            self._failed.add(run_id)
            self._condition.notify_all()
        if self._widgets is not None:
            await self._widgets.abort_run(run_id)

    async def operation_run_id(self, session_key: str, operation_key: str) -> UUID | None:
        async with self._condition:
            return next(
                (
                    run_id
                    for run_id, pending in self._pending.items()
                    if (session_key, operation_key) in pending
                ),
                None,
            )

    async def wait_until_settled(self, run_id: UUID) -> None:
        try:
            with anyio.fail_after(self._timeout):
                async with self._condition:
                    await self._condition.wait_for(lambda: not self._pending.get(run_id))
                self._require_healthy(run_id)
                if self._widgets is not None:
                    await self._widgets.wait_until_settled(run_id)
                self._require_healthy(run_id)
        except TimeoutError as exc:
            raise AgentSessionError(
                "run_state_unknown", "Host operations have not settled"
            ) from exc

    def _require_healthy(self, run_id: UUID) -> None:
        if run_id in self._failed:
            raise AgentSessionError("runtime_contract_error", "Host workflow observation failed")


class HostObservationFactory:
    def __init__(
        self,
        coordinator: AgentRunCoordinator,
        attributions: OperationRunAttributionRegistry,
        settlement: HostRunSettlement,
        factories: Iterable[BridgeSessionObserverFactory],
        *,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._coordinator = coordinator
        self._attributions = attributions
        self._settlement = settlement
        self._factories = tuple(factories)
        self._timeout = timeout_seconds

    def create(self, session_key: str, endpoint_slug: str) -> BridgeObserver | None:
        target = self._coordinator.target_for_endpoint(endpoint_slug)
        if target is None:
            return None
        observers = tuple(
            observer
            for factory in self._factories
            if (observer := factory.create(session_key, endpoint_slug)) is not None
        )
        return _HostObserver(
            target.target_id,
            self._coordinator,
            self._attributions,
            self._settlement,
            observers,
            self._timeout,
        )


class _HostObserver:
    def __init__(
        self,
        target_id: str,
        coordinator: AgentRunCoordinator,
        attributions: OperationRunAttributionRegistry,
        settlement: HostRunSettlement,
        observers: tuple[BridgeObserver, ...],
        timeout_seconds: float,
    ) -> None:
        self._target_id = target_id
        self._coordinator = coordinator
        self._attributions = attributions
        self._settlement = settlement
        self._observers = observers
        self._timeout = timeout_seconds

    async def observe(self, event: BridgeObservation) -> None:
        run_id = await self._coordinator.active_run_id(self._target_id)
        try:
            with anyio.fail_after(self._timeout):
                if isinstance(event, ToolCallCompleted):
                    run_id = await self._settlement.operation_run_id(
                        event.session_key, event.operation_key
                    )
                    attribution = await self._attributions.get(
                        event.session_key, event.operation_key
                    )
                    run_id = attribution.run_id if attribution is not None else run_id
                if isinstance(event, ToolCallStarted) and run_id is not None:
                    await self._settlement.start(run_id, event.session_key, event.operation_key)
                for observer in self._observers:
                    await observer.observe(event)
        except BaseException as exc:
            if run_id is not None:
                with anyio.CancelScope(shield=True):
                    await self._settlement.fail(run_id)
            if not isinstance(exc, Exception):
                raise
        finally:
            if isinstance(event, ToolCallCompleted) and run_id is not None:
                with anyio.CancelScope(shield=True):
                    await self._settlement.complete(run_id, event.session_key, event.operation_key)
