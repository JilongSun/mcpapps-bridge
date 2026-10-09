from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID

import anyio
from anyio.abc import TaskStatus
from anyio.lowlevel import checkpoint
import pytest
from contextlib import aclosing
from mabrid.application.agent_host import (
    AgentRunEvent,
    AgentRunStarted,
    AgentRunCompleted,
    AgentRunResult,
    ToolActivityEvent,
)
from mabrid.application.mcp_apps import WidgetEvent

from mabrid.bridge import (
    ToolCallStarted,
    ToolCallCompleted,
    ToolCallResult,
    BridgeFailure,
    BridgeFailureCode,
)
from mabrid.application.agent_host import (
    AgentOperationAttributionObserverFactory,
    AgentToolActivityObserverFactory,
    InMemoryToolActivityStore,
    InMemoryOperationRunAttributionRegistry,
    ToolInvocationStarted,
    ToolInvocationCompleted,
    ToolInvocationFailed,
)
from mabrid.application.gateway.sessions import CompositeBridgeSessionObserverFactory

from mabrid.application.agent_host import (
    AgentAdapterCompleted,
    AgentAdapterEvent,
    AgentAdapterTextDelta,
    AgentEndpointAssignment,
    AgentHostService,
    AgentMessage,
    AgentRunCoordinator,
    AgentRuntimeInterface,
    AgentRuntimeProfile,
    AgentTarget,
    OperationRunAttribution,
    StartRunCommand,
)
from mabrid.application.host import (
    HostAgentEvent,
    HostEventStream,
    HostWidgetEvent,
    HostToolEvent,
    compose_host_capabilities,
)
from unittest.mock import AsyncMock
from mabrid.bridge import (
    ToolsPublished,
    ToolDescriptor,
    BridgeErrorRaised,
    ResourceRead,
    ReadResourceResult,
    ResourceContent,
)
from mabrid.application.mcp_apps import (
    ApplicationResourceContent,
    InMemoryWidgetEventStore,
    WidgetCreated,
    WidgetInstance,
    WidgetToolResult,
)

PROFILE = AgentRuntimeProfile(
    integration_kind="fixture",
    interface=AgentRuntimeInterface.OPENAI_CHAT_COMPLETIONS,
)
TARGET = AgentTarget(
    target_id="fixture-target",
    runtime_profile=PROFILE,
    endpoint_assignment=AgentEndpointAssignment(endpoint_slug="fixture-endpoint"),
)


class WidgetProducingAdapter:
    def __init__(self, widget_events: InMemoryWidgetEventStore) -> None:
        self._widget_events = widget_events

    @property
    def profile(self) -> AgentRuntimeProfile:
        return PROFILE

    async def run(self, command: StartRunCommand) -> AsyncGenerator[AgentAdapterEvent, None]:
        yield AgentAdapterTextDelta(delta="Hello")
        await self._widget_events.append(
            WidgetCreated(
                widget=WidgetInstance(
                    run_id=command.run_id,
                    target_id=TARGET.target_id,
                    session_key="session-1",
                    operation_key="operation-1",
                    tool_name="inspect",
                    tool_result=WidgetToolResult(
                        content=({"type": "text", "text": "completed"},),
                    ),
                    application_resource_uri="ui://fixture/inspect",
                    resource_contents=(
                        ApplicationResourceContent(
                            uri="ui://fixture/inspect",
                            text="<p>fixture</p>",
                        ),
                    ),
                )
            )
        )
        yield AgentAdapterCompleted()


class SignalingWidgetEventStore(InMemoryWidgetEventStore):
    def __init__(self) -> None:
        super().__init__()
        self.settling_started = anyio.Event()

    async def wait_until_settled(self, run_id) -> None:
        self.settling_started.set()
        await super().wait_until_settled(run_id)


def _command() -> StartRunCommand:
    return StartRunCommand(
        model="fixture-target",
        messages=(AgentMessage(role="user", content="Say hello"),),
    )


async def test_widget_reader_wakes_for_its_run_without_agent_polling() -> None:
    store = InMemoryWidgetEventStore()
    command = _command()
    waiting = anyio.Event()
    delivered = anyio.Event()
    received = []

    async def receive() -> None:
        waiting.set()
        received.extend(await store.wait_for_events(command.run_id, after=0))
        delivered.set()

    async def publish(run_id: UUID, operation_key: str) -> None:
        await store.append(
            WidgetCreated(
                widget=WidgetInstance(
                    run_id=run_id,
                    target_id=TARGET.target_id,
                    session_key="session",
                    operation_key=operation_key,
                    tool_name="inspect",
                    tool_result=WidgetToolResult(),
                    application_resource_uri="ui://fixture/inspect",
                    resource_contents=(
                        ApplicationResourceContent(
                            uri="ui://fixture/inspect", text="<p>fixture</p>"
                        ),
                    ),
                )
            )
        )

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(receive)
        await waiting.wait()
        await publish(_command().run_id, "other-run")
        await checkpoint()
        assert not delivered.is_set()
        await publish(command.run_id, "first")
        with anyio.fail_after(0.5):
            await delivered.wait()
    assert len(received) == 1
    await publish(command.run_id, "second")
    with anyio.fail_after(0.5):
        [later] = await store.wait_for_events(command.run_id, after=1)
    assert isinstance(later, WidgetCreated)
    assert later.widget.operation_key == "second"


@pytest.mark.parametrize("outcome", ["success", "tool_error", "transport_failure"])
async def test_tool_activity_preserves_results_and_uses_public_invocation_identity(
    outcome: str,
) -> None:
    store = InMemoryToolActivityStore()
    registry = InMemoryOperationRunAttributionRegistry()
    coordinator = AgentRunCoordinator((TARGET,))
    factory = CompositeBridgeSessionObserverFactory(
        (
            AgentOperationAttributionObserverFactory(coordinator, registry),
            AgentToolActivityObserverFactory(registry, store),
        )
    )
    observer = factory.create("session", "fixture-endpoint")
    assert observer is not None
    command = _command()
    await observer.observe(
        ToolCallStarted(session_key="session", operation_key="unattributed", tool_name="inspect")
    )
    assert await store.list_for_run(command.run_id) == ()
    await coordinator.start_run(TARGET.target_id, command.run_id)
    await observer.observe(
        ToolCallStarted(
            session_key="session",
            operation_key="operation",
            tool_name="inspect",
            arguments={"value": 42},
        )
    )
    result = ToolCallResult(
        content=({"type": "text", "text": "fixture"},),
        structured_content={"value": 42},
        metadata={"fixture": True},
        is_error=outcome == "tool_error",
    )
    await observer.observe(
        ToolCallCompleted(
            session_key="session",
            operation_key="operation",
            result=result if outcome != "transport_failure" else None,
            failure=BridgeFailure(
                code=BridgeFailureCode.UPSTREAM_TRANSPORT,
                message="fixture transport failure",
                binding_key="private-binding",
            )
            if outcome == "transport_failure"
            else None,
        )
    )
    started, finished = await store.wait_for_events(command.run_id, after=0)
    assert isinstance(started, ToolInvocationStarted)
    assert started.arguments == {"value": 42}
    assert started.tool_invocation_id == finished.tool_invocation_id
    assert await store.invocation_id("session", "operation") == started.tool_invocation_id
    assert "session_key" not in started.model_dump()
    assert "operation_key" not in started.model_dump()
    if outcome == "success":
        assert isinstance(finished, ToolInvocationCompleted)
        assert finished.result.model_dump() == result.model_dump()
    else:
        assert isinstance(finished, ToolInvocationFailed)
        assert finished.error_code == (
            "tool_error" if outcome == "tool_error" else "upstream_transport"
        )
        if outcome == "tool_error":
            assert finished.result is not None
            assert finished.result.model_dump() == result.model_dump()
        else:
            assert finished.result is None
            assert "private-binding" not in finished.model_dump_json()


async def test_host_stream_merges_widget_before_run_terminal_event() -> None:
    widget_events = InMemoryWidgetEventStore()
    coordinator = AgentRunCoordinator((TARGET,))
    agent_host = AgentHostService(
        TARGET,
        WidgetProducingAdapter(widget_events),
        coordinator,
    )
    stream = HostEventStream(agent_host, widget_events)
    command = _command()

    events = [event async for event in stream.run_events(command)]

    assert [event.sequence for event in events] == [1, 2, 3, 4, 5]
    assert [event.kind for event in events] == [
        "host.agent",
        "host.agent",
        "host.widget",
        "host.agent",
        "host.agent",
    ]
    assert isinstance(events[0], HostAgentEvent)
    assert events[0].event.kind == "run.started"
    assert isinstance(events[2], HostWidgetEvent)
    assert events[2].event.kind == "widget.created"
    assert isinstance(events[-1], HostAgentEvent)
    assert events[-1].event.kind == "run.completed"
    assert all(event.run_id == command.run_id for event in events)
    assert await coordinator.active_run_id(TARGET.target_id) is None


async def test_host_stream_delivers_widget_while_provider_is_paused() -> None:
    entered = anyio.Event()
    resume = anyio.Event()
    closed = anyio.Event()

    class PausedAdapter:
        profile = PROFILE

        async def run(self, command: StartRunCommand) -> AsyncGenerator[AgentAdapterEvent, None]:
            try:
                entered.set()
                await resume.wait()
                yield AgentAdapterCompleted()
            finally:
                closed.set()

    store = InMemoryWidgetEventStore()
    coordinator = AgentRunCoordinator((TARGET,))
    service = AgentHostService(TARGET, PausedAdapter(), coordinator)
    command = _command()
    stream = HostEventStream(service, store).run_events(command)
    assert (await anext(stream)).event.kind == "run.started"
    received = []
    delivered = anyio.Event()

    async def receive() -> None:
        received.append(await anext(stream))
        delivered.set()

    try:
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(receive)
            await entered.wait()
            await store.append(
                WidgetCreated(
                    widget=WidgetInstance(
                        run_id=command.run_id,
                        target_id=TARGET.target_id,
                        session_key="session",
                        operation_key="operation",
                        tool_name="inspect",
                        tool_result=WidgetToolResult(),
                        application_resource_uri="ui://fixture/inspect",
                        resource_contents=(
                            ApplicationResourceContent(
                                uri="ui://fixture/inspect", text="<p>fixture</p>"
                            ),
                        ),
                    )
                )
            )
            with anyio.fail_after(0.5):
                await delivered.wait()
        assert isinstance(received[0], HostWidgetEvent)
        assert not resume.is_set()
        assert await coordinator.active_run_id(TARGET.target_id) == command.run_id
    finally:
        await stream.aclose()
    assert closed.is_set()
    assert await coordinator.active_run_id(TARGET.target_id) is None


@pytest.mark.parametrize("widget_outcome", ["disabled", "success", "failure"])
async def test_composed_tools_and_widgets_arrive_without_assistant_deltas(
    widget_outcome: str,
) -> None:
    entered = anyio.Event()
    resume = anyio.Event()
    closed = anyio.Event()

    class PausedAdapter:
        profile = PROFILE

        async def run(self, command: StartRunCommand) -> AsyncGenerator[AgentAdapterEvent, None]:
            try:
                entered.set()
                await resume.wait()
                yield AgentAdapterCompleted()
            finally:
                closed.set()

    repository = AsyncMock()
    repository.get_unsettled_run.return_value = None
    composition = await compose_host_capabilities(
        TARGET, PausedAdapter(), repository, mcp_apps_enabled=widget_outcome != "disabled"
    )
    observer = composition.bridge_observer_factory.create("session", "fixture-endpoint")
    assert observer is not None
    await observer.observe(
        ToolsPublished(
            session_key="session",
            tools=(ToolDescriptor(name="inspect", ui_resource_uri="ui://fixture/inspect"),),
        )
    )
    command = _command()
    stream = composition.events.run_events(command)
    first = await anext(stream)
    assert isinstance(first, HostAgentEvent) and first.event.kind == "run.started"
    received = []
    delivered = anyio.Event()
    expected_count = 2 if widget_outcome == "disabled" else 3

    async def receive() -> None:
        for _index in range(expected_count):
            received.append(await anext(stream))
        delivered.set()

    try:
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(receive)
            await entered.wait()
            await observer.observe(
                ToolCallStarted(
                    session_key="session",
                    operation_key="operation",
                    tool_name="inspect",
                    arguments={"value": 42},
                )
            )
            await observer.observe(
                ToolCallCompleted(
                    session_key="session",
                    operation_key="operation",
                    result=ToolCallResult(structured_content={"value": 42}),
                )
            )
            if widget_outcome == "success":
                await observer.observe(
                    ResourceRead(
                        session_key="session",
                        operation_key="operation",
                        requested_uri="ui://fixture/inspect",
                        result=ReadResourceResult(
                            contents=(
                                ResourceContent(
                                    uri="ui://fixture/inspect",
                                    mime_type="text/html;profile=mcp-app",
                                    text="<p>fixture</p>",
                                ),
                            )
                        ),
                    )
                )
            elif widget_outcome == "failure":
                await observer.observe(
                    BridgeErrorRaised(
                        session_key="session",
                        operation_key="operation",
                        operation="application_resource_load",
                        failure=BridgeFailure(
                            code=BridgeFailureCode.UPSTREAM_PROTOCOL, message="widget unavailable"
                        ),
                    )
                )
            with anyio.fail_after(0.5):
                await delivered.wait()
        assert not resume.is_set()
        assert [event.sequence for event in (first, *received)] == list(
            range(1, expected_count + 2)
        )
        assert all(event.run_id == command.run_id for event in received)
        assert isinstance(received[0], HostToolEvent) and isinstance(
            received[0].event, ToolInvocationStarted
        )
        assert isinstance(received[1], HostToolEvent) and isinstance(
            received[1].event, ToolInvocationCompleted
        )
        assert received[1].event.result.structured_content == {"value": 42}
        if widget_outcome != "disabled":
            assert isinstance(received[2], HostWidgetEvent)
            assert received[2].tool_invocation_id == received[0].event.tool_invocation_id
            assert received[2].event.kind == (
                "widget.created" if widget_outcome == "success" else "widget.failed"
            )
    finally:
        await stream.aclose()
    assert closed.is_set()
    assert await composition.agent_host.coordinator.active_run_id(TARGET.target_id) is None


async def test_host_stream_without_mcp_apps_preserves_agent_events() -> None:
    coordinator = AgentRunCoordinator((TARGET,))
    agent_host = AgentHostService(
        TARGET,
        WidgetProducingAdapter(InMemoryWidgetEventStore()),
        coordinator,
    )
    stream = HostEventStream(agent_host)

    events = [event async for event in stream.run_events(_command())]

    assert all(isinstance(event, HostAgentEvent) for event in events)
    assert [event.event.kind for event in events] == [
        "run.started",
        "assistant.text.delta",
        "assistant.text.completed",
        "run.completed",
    ]


async def test_host_stream_waits_for_pending_widget_before_run_terminal() -> None:
    widget_events = SignalingWidgetEventStore()
    coordinator = AgentRunCoordinator((TARGET,))
    agent_host = AgentHostService(
        TARGET,
        WidgetProducingAdapter(InMemoryWidgetEventStore()),
        coordinator,
    )
    command = _command()
    attribution = OperationRunAttribution(
        run_id=command.run_id,
        target_id=TARGET.target_id,
        session_key="session-1",
        operation_key="operation-1",
    )
    await widget_events.start_operation(attribution)
    stream = HostEventStream(agent_host, widget_events).run_events(command)
    assert (await anext(stream)).event.kind == "run.started"
    assert (await anext(stream)).event.kind == "assistant.text.delta"
    assert (await anext(stream)).event.kind == "assistant.text.completed"
    terminal_received = anyio.Event()
    received: list[HostAgentEvent | HostWidgetEvent | HostToolEvent] = []

    async def receive_settled_events() -> None:
        received.append(await anext(stream))
        received.append(await anext(stream))
        terminal_received.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(receive_settled_events)
        await widget_events.settling_started.wait()
        assert terminal_received.is_set() is False
        assert await coordinator.active_run_id(TARGET.target_id) == command.run_id
        await widget_events.append(
            WidgetCreated(
                widget=WidgetInstance(
                    run_id=command.run_id,
                    target_id=TARGET.target_id,
                    session_key="session-1",
                    operation_key="operation-1",
                    tool_name="inspect",
                    tool_result=WidgetToolResult(),
                    application_resource_uri="ui://fixture/inspect",
                    resource_contents=(
                        ApplicationResourceContent(
                            uri="ui://fixture/inspect",
                            text="<p>fixture</p>",
                        ),
                    ),
                )
            )
        )

    assert [event.kind for event in received] == ["host.widget", "host.agent"]
    assert isinstance(received[-1], HostAgentEvent)
    assert received[-1].event.kind == "run.completed"
    await stream.aclose()
    assert await coordinator.active_run_id(TARGET.target_id) is None


@pytest.mark.parametrize("exit_mode", ["close", "cancel", "widget_error", "tool_error", "complete"])
async def test_merger_joins_all_readers_on_every_exit_path(exit_mode: str) -> None:
    class CountingWidgets(InMemoryWidgetEventStore):
        def __init__(self) -> None:
            super().__init__()
            self.readers = 0
            self.waiting = anyio.Event()
            self.fail_reads = False

        async def wait_for_events(self, run_id: UUID, after: int) -> tuple[WidgetEvent, ...]:
            self.readers += 1
            self.waiting.set()
            try:
                if self.fail_reads:
                    raise RuntimeError("fixture widget reader failure")
                return await super().wait_for_events(run_id, after)
            finally:
                self.readers -= 1

    class CountingTools(InMemoryToolActivityStore):
        def __init__(self) -> None:
            super().__init__()
            self.readers = 0
            self.waiting = anyio.Event()
            self.fail_reads = exit_mode == "tool_error"

        async def wait_for_events(self, run_id: UUID, after: int) -> tuple[ToolActivityEvent, ...]:
            self.readers += 1
            self.waiting.set()
            try:
                if self.fail_reads:
                    raise RuntimeError("fixture tool reader failure")
                return await super().wait_for_events(run_id, after)
            finally:
                self.readers -= 1

    coordinator = AgentRunCoordinator((TARGET,))
    entered = anyio.Event()
    resume = anyio.Event()
    closed = anyio.Event()

    class Source:
        async def run_events(self, command: StartRunCommand) -> AsyncGenerator[AgentRunEvent, None]:
            await coordinator.start_run(TARGET.target_id, command.run_id)
            try:
                yield AgentRunStarted(run_id=command.run_id, sequence=1, model=TARGET.target_id)
                entered.set()
                await resume.wait()
                yield AgentRunCompleted(
                    run_id=command.run_id,
                    sequence=2,
                    result=AgentRunResult(
                        run_id=command.run_id, model=TARGET.target_id, output_text="Fixture"
                    ),
                )
            finally:
                with anyio.CancelScope(shield=True):
                    await coordinator.finish_run(TARGET.target_id, command.run_id)
                closed.set()

    widgets = CountingWidgets()
    tools = CountingTools()
    command = _command()
    stream = HostEventStream(Source(), widgets, tool_activity=tools).run_events(command)
    await anext(stream)
    try:
        if exit_mode == "tool_error":
            with pytest.raises(RuntimeError, match="tool reader failure"):
                await anext(stream)
        else:
            async with anyio.create_task_group() as tasks:

                async def receive_widget() -> None:
                    assert isinstance(await anext(stream), HostWidgetEvent)

                tasks.start_soon(receive_widget)
                await entered.wait()
                await widgets.waiting.wait()
                await tools.waiting.wait()
                async with aclosing(WidgetProducingAdapter(widgets).run(command)) as publisher:
                    await anext(publisher)
                    await anext(publisher)
            assert tools.readers == 1
            if exit_mode == "widget_error":
                widgets.fail_reads = True
                with pytest.raises(RuntimeError, match="widget reader failure"):
                    await anext(stream)
            elif exit_mode == "cancel":
                widgets.waiting = anyio.Event()

                async def receive_cancelled(*, task_status: TaskStatus[anyio.CancelScope]) -> None:
                    with anyio.CancelScope() as scope:
                        task_status.started(scope)
                        await anext(stream)

                async with anyio.create_task_group() as tasks:
                    scope = await tasks.start(receive_cancelled)
                    await widgets.waiting.wait()
                    scope.cancel()
            elif exit_mode == "complete":
                resume.set()
                events = [event async for event in stream]
                assert isinstance(events[-1], HostAgentEvent)
                assert events[-1].event.kind == "run.completed"
    finally:
        with anyio.fail_after(0.5):
            await stream.aclose()
    assert closed.is_set()
    assert widgets.readers == tools.readers == 0
    assert await coordinator.active_run_id(TARGET.target_id) is None
