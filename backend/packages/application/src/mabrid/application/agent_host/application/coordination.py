"""Agent Target endpoint ownership and active Run coordination."""

from __future__ import annotations

from asyncio import Lock
from collections.abc import Iterable
from uuid import UUID

from ..contracts import AgentTarget


class AgentTargetConflictError(ValueError):
    """Raised when Agent Target identities or endpoint assignments conflict."""


class AgentRunConflictError(RuntimeError):
    """Raised when a Target already has an active Run."""


class AgentRunCoordinator:
    def __init__(self, targets: Iterable[AgentTarget]) -> None:
        self._targets_by_id: dict[str, AgentTarget] = {}
        self._targets_by_endpoint: dict[str, AgentTarget] = {}
        self._active_runs: dict[str, UUID] = {}
        self._lock = Lock()
        for target in targets:
            if target.target_id in self._targets_by_id:
                raise AgentTargetConflictError(
                    f"Agent Target ID {target.target_id!r} is configured more than once"
                )
            endpoint_slug = target.endpoint_assignment.endpoint_slug
            owner = self._targets_by_endpoint.get(endpoint_slug)
            if owner is not None:
                raise AgentTargetConflictError(
                    f"Gateway endpoint {endpoint_slug!r} is assigned to both Agent Targets "
                    f"{owner.target_id!r} and {target.target_id!r}"
                )
            self._targets_by_id[target.target_id] = target
            self._targets_by_endpoint[endpoint_slug] = target

    def target_for_endpoint(self, endpoint_slug: str) -> AgentTarget | None:
        return self._targets_by_endpoint.get(endpoint_slug)

    async def active_run_id(self, target_id: str) -> UUID | None:
        async with self._lock:
            return self._active_runs.get(target_id)

    async def start_run(self, target_id: str, run_id: UUID) -> None:
        if target_id not in self._targets_by_id:
            raise ValueError(f"Unknown Agent Target {target_id!r}")
        async with self._lock:
            active_run_id = self._active_runs.get(target_id)
            if active_run_id is not None:
                raise AgentRunConflictError(
                    f"Agent Target {target_id!r} already has active Run {active_run_id}"
                )
            self._active_runs[target_id] = run_id

    async def finish_run(self, target_id: str, run_id: UUID) -> None:
        async with self._lock:
            active_run_id = self._active_runs.get(target_id)
            if active_run_id != run_id:
                raise RuntimeError(
                    f"Run {run_id} is not the active Run for Agent Target {target_id!r}"
                )
            del self._active_runs[target_id]
