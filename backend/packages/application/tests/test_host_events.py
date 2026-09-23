from __future__ import annotations

from collections.abc import AsyncIterator

import anyio

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
from mabrid.application.host import HostAgentEvent, HostEventStream, HostWidgetEvent
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

    async def run(self, command: StartRunCommand) -> AsyncIterator[AgentAdapterEvent]:
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
    received: list[HostAgentEvent | HostWidgetEvent] = []

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
