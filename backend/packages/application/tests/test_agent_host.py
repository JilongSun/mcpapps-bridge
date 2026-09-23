from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from mabrid.bridge import ToolCallStarted
from mabrid.application.agent_host import (
    AgentAdapterCompleted,
    AgentAdapterEvent,
    AgentAdapterTextDelta,
    AgentCapability,
    AgentEndpointAssignment,
    AgentHostService,
    AgentOperationAttributionObserverFactory,
    AgentMessage,
    AgentRunConflictError,
    AgentRunCoordinator,
    AgentRunError,
    AgentRuntime,
    AgentRuntimeInterface,
    AgentRuntimeProfile,
    AgentTarget,
    AgentTargetConflictError,
    InMemoryOperationRunAttributionRegistry,
    StartRunCommand,
    TokenUsage,
)

PROFILE = AgentRuntimeProfile(
    integration_kind="fixture",
    interface=AgentRuntimeInterface.OPENAI_CHAT_COMPLETIONS,
    capabilities=frozenset(
        {
            AgentCapability.TEXT_GENERATION,
            AgentCapability.TOKEN_USAGE,
        }
    ),
)

TARGET = AgentTarget(
    target_id="fixture-target",
    runtime_profile=PROFILE,
    endpoint_assignment=AgentEndpointAssignment(endpoint_slug="fixture-endpoint"),
)


class SuccessfulAdapter:
    @property
    def profile(self) -> AgentRuntimeProfile:
        return PROFILE

    async def run(self, command: StartRunCommand) -> AsyncGenerator[AgentAdapterEvent, None]:
        assert command.model == TARGET.target_id
        yield AgentAdapterTextDelta(delta="Hello")
        yield AgentAdapterTextDelta(delta=" world")
        yield AgentAdapterCompleted(
            finish_reason="stop",
            usage=TokenUsage(input_tokens=3, output_tokens=2),
        )


class FailingAdapter:
    @property
    def profile(self) -> AgentRuntimeProfile:
        return PROFILE

    async def run(self, command: StartRunCommand) -> AsyncGenerator[AgentAdapterEvent, None]:
        raise RuntimeError(f"Provider unavailable for {command.model}")
        yield


def _command() -> StartRunCommand:
    return StartRunCommand(
        model="caller-selected-model",
        messages=(AgentMessage(role="user", content="Say hello"),),
    )


def _service(runtime: AgentRuntime) -> AgentHostService:
    return AgentHostService(TARGET, runtime, AgentRunCoordinator((TARGET,)))


async def test_agent_host_emits_provider_neutral_ordered_events() -> None:
    service = _service(SuccessfulAdapter())

    events = [event async for event in service.run_events(_command())]

    assert [event.kind for event in events] == [
        "run.started",
        "assistant.text.delta",
        "assistant.text.delta",
        "assistant.text.completed",
        "run.completed",
    ]
    assert [event.sequence for event in events] == [1, 2, 3, 4, 5]
    completed = events[-1]
    assert completed.kind == "run.completed"
    assert completed.result.model == TARGET.target_id
    assert completed.result.output_text == "Hello world"
    assert completed.result.usage.total_tokens == 5


async def test_agent_host_complete_returns_the_terminal_result() -> None:
    service = _service(SuccessfulAdapter())

    result = await service.complete(_command())

    assert result.output_text == "Hello world"
    assert result.finish_reason == "stop"
    assert await service.coordinator.active_run_id(TARGET.target_id) is None


async def test_agent_run_stays_active_until_terminal_event_is_consumed() -> None:
    service = _service(SuccessfulAdapter())
    command = _command()
    stream = service.run_events(command)

    terminal = None
    while terminal is None:
        event = await anext(stream)
        if event.kind == "run.completed":
            terminal = event

    assert await service.coordinator.active_run_id(TARGET.target_id) == command.run_id
    await stream.aclose()
    assert await service.coordinator.active_run_id(TARGET.target_id) is None


async def test_closing_run_releases_outbound_runtime_stream() -> None:
    class ClosableAdapter(SuccessfulAdapter):
        closed = False

        async def run(self, command: StartRunCommand) -> AsyncGenerator[AgentAdapterEvent, None]:
            try:
                yield AgentAdapterTextDelta(delta="partial")
                yield AgentAdapterCompleted()
            finally:
                self.closed = True

    adapter = ClosableAdapter()
    service = _service(adapter)
    stream = service.run_events(_command())
    assert (await anext(stream)).kind == "run.started"
    assert (await anext(stream)).kind == "assistant.text.delta"

    await stream.aclose()

    assert adapter.closed is True
    assert await service.coordinator.active_run_id(TARGET.target_id) is None


async def test_agent_host_normalizes_adapter_failure() -> None:
    adapter: AgentRuntime = FailingAdapter()
    service = _service(adapter)

    events = [event async for event in service.run_events(_command())]

    assert [event.kind for event in events] == ["run.started", "run.failed"]
    assert events[-1].sequence == 2
    assert await service.coordinator.active_run_id(TARGET.target_id) is None
    with pytest.raises(AgentRunError, match="Provider unavailable for fixture-target"):
        await service.complete(_command())


async def test_agent_host_advertises_only_its_canonical_target() -> None:
    service = _service(SuccessfulAdapter())

    models = await service.list_models()

    assert [(model.model_id, model.owned_by) for model in models] == [("fixture-target", "fixture")]
    assert service.runtime_profile == PROFILE
    assert service.target.endpoint_assignment.endpoint_slug == "fixture-endpoint"


def test_agent_host_rejects_a_runtime_that_does_not_match_the_target() -> None:
    mismatched_profile = PROFILE.model_copy(update={"integration_kind": "other-fixture"})

    class MismatchedRuntime(SuccessfulAdapter):
        @property
        def profile(self) -> AgentRuntimeProfile:
            return mismatched_profile

    with pytest.raises(ValueError, match="does not match Agent Target"):
        _service(MismatchedRuntime())


def test_run_coordinator_rejects_shared_endpoint_assignment() -> None:
    conflicting_target = TARGET.model_copy(update={"target_id": "other-target"})

    with pytest.raises(AgentTargetConflictError, match="assigned to both Agent Targets"):
        AgentRunCoordinator((TARGET, conflicting_target))


async def test_agent_host_rejects_a_second_active_run() -> None:
    service = _service(SuccessfulAdapter())
    first_run = service.run_events(_command())
    started = await anext(first_run)

    assert started.kind == "run.started"
    assert await service.coordinator.active_run_id(TARGET.target_id) == started.run_id
    with pytest.raises(AgentRunConflictError, match="already has active Run"):
        await anext(service.run_events(_command()))

    await first_run.aclose()
    assert await service.coordinator.active_run_id(TARGET.target_id) is None
    events = [event async for event in service.run_events(_command())]
    assert events[-1].kind == "run.completed"


async def test_tool_operation_captures_the_active_run_at_start() -> None:
    coordinator = AgentRunCoordinator((TARGET,))
    registry = InMemoryOperationRunAttributionRegistry()
    observer = AgentOperationAttributionObserverFactory(coordinator, registry).create(
        "session-1",
        "fixture-endpoint",
    )
    assert observer is not None
    run_id = _command().run_id
    await coordinator.start_run(TARGET.target_id, run_id)

    await observer.observe(
        ToolCallStarted(
            session_key="session-1",
            operation_key="operation-1",
            tool_name="inspect",
        )
    )
    await coordinator.finish_run(TARGET.target_id, run_id)

    attribution = await registry.get("session-1", "operation-1")
    assert attribution is not None
    assert attribution.run_id == run_id
    assert attribution.target_id == TARGET.target_id


async def test_tool_operation_without_an_active_run_is_not_attributed() -> None:
    coordinator = AgentRunCoordinator((TARGET,))
    registry = InMemoryOperationRunAttributionRegistry()
    observer = AgentOperationAttributionObserverFactory(coordinator, registry).create(
        "session-1",
        "fixture-endpoint",
    )
    assert observer is not None

    await observer.observe(
        ToolCallStarted(
            session_key="session-1",
            operation_key="operation-1",
            tool_name="inspect",
        )
    )

    assert await registry.get("session-1", "operation-1") is None


async def test_tool_operation_attribution_cannot_move_to_a_later_run() -> None:
    coordinator = AgentRunCoordinator((TARGET,))
    registry = InMemoryOperationRunAttributionRegistry()
    observer = AgentOperationAttributionObserverFactory(coordinator, registry).create(
        "session-1",
        "fixture-endpoint",
    )
    assert observer is not None
    event = ToolCallStarted(
        session_key="session-1",
        operation_key="operation-1",
        tool_name="inspect",
    )
    first_run_id = _command().run_id
    await coordinator.start_run(TARGET.target_id, first_run_id)
    await observer.observe(event)
    await coordinator.finish_run(TARGET.target_id, first_run_id)
    second_run_id = _command().run_id
    await coordinator.start_run(TARGET.target_id, second_run_id)

    with pytest.raises(ValueError, match="different Agent Run attribution"):
        await observer.observe(event)

    attribution = await registry.get("session-1", "operation-1")
    assert attribution is not None
    assert attribution.run_id == first_run_id
    await coordinator.finish_run(TARGET.target_id, second_run_id)
