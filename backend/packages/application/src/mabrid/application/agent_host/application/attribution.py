"""Capture Agent Run ownership when Gateway tool operations start."""

from __future__ import annotations

from asyncio import Lock
from typing import Protocol

from mabrid.bridge import BridgeObservation, BridgeObserver, ToolCallStarted

from ..contracts import OperationRunAttribution
from .coordination import AgentRunCoordinator


class OperationRunAttributionRegistry(Protocol):
    async def record(self, attribution: OperationRunAttribution) -> None: ...

    async def get(
        self,
        session_key: str,
        operation_key: str,
    ) -> OperationRunAttribution | None: ...


class InMemoryOperationRunAttributionRegistry:
    def __init__(self) -> None:
        self._attributions: dict[tuple[str, str], OperationRunAttribution] = {}
        self._lock = Lock()

    async def record(self, attribution: OperationRunAttribution) -> None:
        key = (attribution.session_key, attribution.operation_key)
        async with self._lock:
            existing = self._attributions.get(key)
            if existing is not None and existing != attribution:
                raise ValueError(
                    "Gateway tool operation already has a different Agent Run attribution: "
                    f"{attribution.session_key}/{attribution.operation_key}"
                )
            self._attributions[key] = attribution

    async def get(
        self,
        session_key: str,
        operation_key: str,
    ) -> OperationRunAttribution | None:
        async with self._lock:
            return self._attributions.get((session_key, operation_key))


class AgentOperationAttributionObserver:
    def __init__(
        self,
        session_key: str,
        target_id: str,
        coordinator: AgentRunCoordinator,
        registry: OperationRunAttributionRegistry,
    ) -> None:
        self._session_key = session_key
        self._target_id = target_id
        self._coordinator = coordinator
        self._registry = registry

    async def observe(self, event: BridgeObservation) -> None:
        if event.session_key != self._session_key:
            raise ValueError(
                f"observation session mismatch: {event.session_key} != {self._session_key}"
            )
        if not isinstance(event, ToolCallStarted):
            return
        run_id = await self._coordinator.active_run_id(self._target_id)
        if run_id is None:
            return
        await self._registry.record(
            OperationRunAttribution(
                run_id=run_id,
                target_id=self._target_id,
                session_key=event.session_key,
                operation_key=event.operation_key,
            )
        )


class AgentOperationAttributionObserverFactory:
    def __init__(
        self,
        coordinator: AgentRunCoordinator,
        registry: OperationRunAttributionRegistry,
    ) -> None:
        self._coordinator = coordinator
        self._registry = registry

    def create(self, session_key: str, endpoint_slug: str) -> BridgeObserver | None:
        target = self._coordinator.target_for_endpoint(endpoint_slug)
        if target is None:
            return None
        return AgentOperationAttributionObserver(
            session_key,
            target.target_id,
            self._coordinator,
            self._registry,
        )
