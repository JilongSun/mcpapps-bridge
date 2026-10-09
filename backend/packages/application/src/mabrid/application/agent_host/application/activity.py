"""Project attributed Gateway tool observations into process-local Run activity."""

from asyncio import Condition
from uuid import UUID, uuid4

from mabrid.bridge import BridgeObservation, BridgeObserver, ToolCallStarted, ToolCallCompleted

from ..contracts import OperationRunAttribution
from ..contracts.activity import (
    ToolActivityEvent,
    ToolInvocationStarted,
    ToolInvocationCompleted,
    ToolInvocationFailed,
    ToolInvocationResult,
)
from .attribution import OperationRunAttributionRegistry


class InMemoryToolActivityStore:
    def __init__(self) -> None:
        self._condition = Condition()
        self._events: dict[UUID, list[ToolActivityEvent]] = {}
        self._invocations: dict[tuple[str, str], ToolInvocationStarted] = {}
        self._completed: set[tuple[str, str]] = set()

    async def record_started(
        self, attribution: OperationRunAttribution, event: ToolCallStarted
    ) -> None:
        key = (event.session_key, event.operation_key)
        async with self._condition:
            if key in self._invocations:
                raise ValueError("Tool invocation already started")
            started = ToolInvocationStarted(
                run_id=attribution.run_id,
                target_id=attribution.target_id,
                tool_invocation_id=uuid4(),
                tool_name=event.tool_name,
                arguments=event.arguments,
                occurred_at=event.observed_at,
            )
            self._invocations[key] = started
            self._events.setdefault(attribution.run_id, []).append(started)
            self._condition.notify_all()

    async def record_completed(self, event: ToolCallCompleted) -> None:
        key = (event.session_key, event.operation_key)
        async with self._condition:
            started = self._invocations.get(key)
            if started is None:
                return
            if key in self._completed:
                raise ValueError("Tool invocation already completed")
            result = (
                ToolInvocationResult.model_validate(event.result.model_dump())
                if event.result is not None
                else None
            )
            if event.failure is not None:
                code, message = event.failure.code.value, event.failure.message
            elif result is None:
                code, message = "missing_tool_result", "Tool invocation completed without a result"
            elif result.is_error:
                code, message = "tool_error", "Tool returned an error result"
            else:
                code, message = None, None
            completed: ToolInvocationCompleted | ToolInvocationFailed
            if code is not None and message is not None:
                completed = ToolInvocationFailed(
                    run_id=started.run_id,
                    target_id=started.target_id,
                    tool_invocation_id=started.tool_invocation_id,
                    tool_name=started.tool_name,
                    occurred_at=event.observed_at,
                    error_code=code,
                    error_message=message,
                    result=result,
                )
            else:
                assert result is not None
                completed = ToolInvocationCompleted(
                    run_id=started.run_id,
                    target_id=started.target_id,
                    tool_invocation_id=started.tool_invocation_id,
                    tool_name=started.tool_name,
                    occurred_at=event.observed_at,
                    result=result,
                )
            self._completed.add(key)
            self._events[started.run_id].append(completed)
            self._condition.notify_all()

    async def invocation_id(self, session_key: str, operation_key: str) -> UUID | None:
        async with self._condition:
            started = self._invocations.get((session_key, operation_key))
            return started.tool_invocation_id if started is not None else None

    async def list_for_run(self, run_id: UUID) -> tuple[ToolActivityEvent, ...]:
        async with self._condition:
            return tuple(self._events.get(run_id, ()))

    async def wait_for_events(self, run_id: UUID, after: int) -> tuple[ToolActivityEvent, ...]:
        if after < 0:
            raise ValueError("Event offset must not be negative")
        async with self._condition:
            await self._condition.wait_for(lambda: len(self._events.get(run_id, ())) > after)
            return tuple(self._events[run_id][after:])


class AgentToolActivityObserverFactory:
    def __init__(
        self, attributions: OperationRunAttributionRegistry, events: InMemoryToolActivityStore
    ) -> None:
        self._attributions = attributions
        self._events = events

    def create(self, session_key: str, endpoint_slug: str) -> BridgeObserver:
        return _ToolActivityObserver(session_key, self._attributions, self._events)


class _ToolActivityObserver:
    def __init__(
        self,
        session_key: str,
        attributions: OperationRunAttributionRegistry,
        events: InMemoryToolActivityStore,
    ) -> None:
        self._session_key = session_key
        self._attributions = attributions
        self._events = events

    async def observe(self, event: BridgeObservation) -> None:
        if event.session_key != self._session_key:
            raise ValueError("Tool activity observation session mismatch")
        if isinstance(event, ToolCallStarted):
            attribution = await self._attributions.get(event.session_key, event.operation_key)
            if attribution is not None:
                await self._events.record_started(attribution, event)
        elif isinstance(event, ToolCallCompleted):
            await self._events.record_completed(event)
