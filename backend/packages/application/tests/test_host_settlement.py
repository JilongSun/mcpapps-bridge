from uuid import uuid4

import anyio
import pytest

from mabrid.application.agent_host import (
    AgentSessionError,
    AgentRunCoordinator,
    AgentTarget,
    AgentRuntimeProfile,
    AgentRuntimeInterface,
    AgentEndpointAssignment,
    InMemoryOperationRunAttributionRegistry,
    AgentOperationAttributionObserverFactory,
    OperationRunAttribution,
)
from mabrid.application.host.settlement import HostRunSettlement, HostObservationFactory
from mabrid.application.agent_host import (
    AgentAdapterCompleted,
    StartRunCommand,
    AgentMessage,
    AgentRunConflictError,
)
from mabrid.application.host.composition import compose_host_capabilities
from unittest.mock import AsyncMock
from mabrid.application.agent_host import AgentHostService, AgentRunCompleted, AgentRunFailed
from mabrid.application.host import HostEventStream, HostAgentEvent
from mabrid.application.mcp_apps import InMemoryWidgetEventStore
from mabrid.bridge import ToolCallStarted, ToolCallCompleted, ToolCallResult


TARGET = AgentTarget(
    target_id="fixture",
    runtime_profile=AgentRuntimeProfile(
        integration_kind="fixture",
        interface=AgentRuntimeInterface.OPENAI_CHAT_COMPLETIONS,
        capabilities=frozenset(),
    ),
    endpoint_assignment=AgentEndpointAssignment(endpoint_slug="fixture"),
)


@pytest.mark.parametrize("timeout", [False, True])
async def test_host_observer_failure_preserves_protocol_and_fails_settlement(timeout: bool) -> None:
    run_id = uuid4()
    coordinator = AgentRunCoordinator((TARGET,))
    await coordinator.start_run(TARGET.target_id, run_id)
    registry = InMemoryOperationRunAttributionRegistry()
    widgets = InMemoryWidgetEventStore()
    settlement = HostRunSettlement(widgets, timeout_seconds=0.1)

    class FailingObserver:
        def create(self, session_key: str, endpoint_slug: str):
            return self

        async def observe(self, event):
            attribution = await registry.get(event.session_key, event.operation_key)
            assert attribution is not None
            await widgets.start_operation(attribution)
            if timeout:
                await anyio.Event().wait()
            raise RuntimeError("fixture failure")

    observer = HostObservationFactory(
        coordinator,
        registry,
        settlement,
        (AgentOperationAttributionObserverFactory(coordinator, registry), FailingObserver()),
        timeout_seconds=0.01,
    ).create("session", "fixture")
    assert observer is not None
    await observer.observe(
        ToolCallStarted(session_key="session", operation_key="operation", tool_name="fixture__tool")
    )
    with pytest.raises(AgentSessionError) as unfinished:
        await settlement.wait_until_settled(run_id)
    assert unfinished.value.code == "run_state_unknown"
    await observer.observe(
        ToolCallCompleted(
            session_key="session", operation_key="operation", result=ToolCallResult(content=())
        )
    )
    with pytest.raises(AgentSessionError) as failure:
        await settlement.wait_until_settled(run_id)
    assert failure.value.code == "runtime_contract_error"
    with anyio.fail_after(0.1):
        await widgets.wait_until_settled(run_id)


async def test_host_settlement_tracks_tool_completion_and_widgets() -> None:
    run_id = uuid4()
    coordinator = AgentRunCoordinator((TARGET,))
    await coordinator.start_run(TARGET.target_id, run_id)
    registry = InMemoryOperationRunAttributionRegistry()
    widgets = InMemoryWidgetEventStore()
    settlement = HostRunSettlement(widgets, timeout_seconds=0.01)
    observer = HostObservationFactory(
        coordinator,
        registry,
        settlement,
        (AgentOperationAttributionObserverFactory(coordinator, registry),),
    ).create("session", "fixture")
    assert observer is not None
    await observer.observe(
        ToolCallStarted(session_key="session", operation_key="operation", tool_name="fixture__tool")
    )
    with pytest.raises(AgentSessionError) as pending:
        await settlement.wait_until_settled(run_id)
    assert pending.value.code == "run_state_unknown"
    attribution = OperationRunAttribution(
        run_id=run_id, target_id=TARGET.target_id, session_key="session", operation_key="operation"
    )
    await widgets.start_operation(attribution)
    await observer.observe(
        ToolCallCompleted(
            session_key="session", operation_key="operation", result=ToolCallResult(content=())
        )
    )
    with pytest.raises(AgentSessionError):
        await settlement.wait_until_settled(run_id)
    await widgets.settle_operation(attribution)
    await settlement.wait_until_settled(run_id)


async def test_application_assembly_restores_ownership_without_remote_probe() -> None:
    from mabrid.application.agent_host import UnsettledSessionRun

    run_id = uuid4()
    repository = AsyncMock()
    repository.get_unsettled_run.return_value = UnsettledSessionRun(
        target_id=TARGET.target_id,
        session_id=uuid4(),
        run_id=run_id,
        runtime_binding_id="old-deployment",
    )

    class Runtime:
        profile = TARGET.runtime_profile

        async def run(self, command):
            raise AssertionError("restored Target must not invoke the runtime")
            yield AgentAdapterCompleted()

    composition = await compose_host_capabilities(TARGET, Runtime(), repository)
    assert composition.sessions is None
    assert composition.mcp_apps is None
    assert await composition.agent_host.coordinator.active_run_id(TARGET.target_id) == run_id
    with pytest.raises(AgentRunConflictError):
        await anext(
            composition.agent_host.run_events(
                StartRunCommand(
                    model=TARGET.target_id, messages=(AgentMessage(role="user", content="Overlap"),)
                )
            )
        )


@pytest.mark.parametrize("fail", [False, True])
async def test_compatibility_run_waits_before_terminal_and_releasing_ownership(fail: bool) -> None:
    coordinator = AgentRunCoordinator((TARGET,))
    settlement = HostRunSettlement(timeout_seconds=0.5)
    command = StartRunCommand(
        model=TARGET.target_id, messages=(AgentMessage(role="user", content="Fixture"),)
    )
    submitted = anyio.Event()

    class Runtime:
        profile = TARGET.runtime_profile

        async def run(self, command):
            await settlement.start(command.run_id, "session", "operation")
            submitted.set()
            yield AgentAdapterCompleted()

    service = AgentHostService(TARGET, Runtime(), coordinator, settlement)
    stream = service.run_events(command)
    assert (await anext(stream)).kind == "run.started"
    terminal = anyio.Event()
    events = []

    async def consume():
        async for event in stream:
            events.append(event)
            if isinstance(event, (AgentRunCompleted, AgentRunFailed)):
                terminal.set()

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(consume)
        await submitted.wait()
        assert not terminal.is_set()
        assert await coordinator.active_run_id(TARGET.target_id) == command.run_id
        if fail:
            await settlement.fail(command.run_id)
            await settlement.complete(command.run_id, "session", "operation")
        else:
            await settlement.complete(command.run_id, "session", "operation")
        with anyio.fail_after(1):
            await terminal.wait()
    assert isinstance(events[-1], AgentRunFailed if fail else AgentRunCompleted)
    assert await coordinator.active_run_id(TARGET.target_id) is None


async def test_host_observer_external_cancellation_propagates_and_aborts_pending() -> None:
    coordinator = AgentRunCoordinator((TARGET,))
    registry = InMemoryOperationRunAttributionRegistry()
    settlement = HostRunSettlement()
    run_id = uuid4()
    await coordinator.start_run(TARGET.target_id, run_id)

    class CancelledObserver:
        def create(self, session_key: str, endpoint_slug: str):
            return self

        async def observe(self, event):
            raise anyio.get_cancelled_exc_class()()

    observer = HostObservationFactory(
        coordinator,
        registry,
        settlement,
        (AgentOperationAttributionObserverFactory(coordinator, registry), CancelledObserver()),
    ).create("session", "fixture")
    assert observer is not None
    with pytest.raises(anyio.get_cancelled_exc_class()):
        await observer.observe(
            ToolCallStarted(session_key="session", operation_key="operation", tool_name="fixture")
        )
    with pytest.raises(anyio.get_cancelled_exc_class()):
        await observer.observe(
            ToolCallCompleted(
                session_key="session", operation_key="operation", result=ToolCallResult(content=())
            )
        )
    with pytest.raises(AgentSessionError):
        await settlement.wait_until_settled(run_id)


async def test_host_presentation_unknown_settlement_does_not_wait_forever() -> None:
    coordinator = AgentRunCoordinator((TARGET,))
    widgets = InMemoryWidgetEventStore()
    settlement = HostRunSettlement(widgets, timeout_seconds=0.01)

    class Runtime:
        profile = TARGET.runtime_profile

        async def run(self, command):
            await widgets.start_operation(
                OperationRunAttribution(
                    run_id=command.run_id,
                    target_id=TARGET.target_id,
                    session_key="session",
                    operation_key="operation",
                )
            )
            yield AgentAdapterCompleted()

    source = AgentHostService(TARGET, Runtime(), coordinator, settlement)
    presentation = HostEventStream(source, widgets, settlement)
    command = StartRunCommand(
        model=TARGET.target_id, messages=(AgentMessage(role="user", content="Fixture"),)
    )
    events = []
    with pytest.raises(AgentSessionError) as error:
        with anyio.fail_after(0.2):
            async for event in presentation.run_events(command):
                events.append(event)
    assert error.value.code == "run_state_unknown"
    assert any(
        isinstance(event, HostAgentEvent) and isinstance(event.event, AgentRunFailed)
        for event in events
    )
    assert await coordinator.active_run_id(TARGET.target_id) == command.run_id
