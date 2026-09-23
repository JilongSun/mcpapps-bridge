"""Merge owned domain events into one ordered Host presentation stream."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import aclosing
from uuid import UUID

from ..agent_host import AgentRunCompleted, AgentRunFailed, AgentRunStarted, StartRunCommand
from ..mcp_apps import WidgetEvent
from .contracts import HostAgentEvent, HostEvent, HostWidgetEvent
from .ports import AgentRunEventSource, WidgetEventReader


class HostEventStream:
    def __init__(
        self,
        agent_runs: AgentRunEventSource,
        widget_events: WidgetEventReader | None = None,
    ) -> None:
        self._agent_runs = agent_runs
        self._widget_events = widget_events

    async def run_events(self, command: StartRunCommand) -> AsyncGenerator[HostEvent, None]:
        sequence = 0
        emitted_widget_count = 0
        async with aclosing(self._agent_runs.run_events(command)) as agent_events:
            async for agent_event in agent_events:
                if isinstance(agent_event, (AgentRunCompleted, AgentRunFailed)):
                    if self._widget_events is not None:
                        await self._widget_events.wait_until_settled(command.run_id)
                pending_widgets = await self._pending_widgets(
                    command.run_id,
                    emitted_widget_count,
                )
                emitted_widget_count += len(pending_widgets)

                if isinstance(agent_event, AgentRunStarted):
                    sequence += 1
                    yield HostAgentEvent(
                        run_id=command.run_id,
                        sequence=sequence,
                        event=agent_event,
                    )
                    continue

                if isinstance(agent_event, (AgentRunCompleted, AgentRunFailed)):
                    for widget_event in pending_widgets:
                        sequence += 1
                        yield _widget_envelope(command.run_id, sequence, widget_event)
                    sequence += 1
                    yield HostAgentEvent(
                        run_id=command.run_id,
                        sequence=sequence,
                        event=agent_event,
                    )
                    continue

                earlier_widgets = tuple(
                    event
                    for event in pending_widgets
                    if _widget_occurred_at(event) <= agent_event.created_at
                )
                later_widgets = tuple(
                    event
                    for event in pending_widgets
                    if _widget_occurred_at(event) > agent_event.created_at
                )
                for widget_event in earlier_widgets:
                    sequence += 1
                    yield _widget_envelope(command.run_id, sequence, widget_event)
                sequence += 1
                yield HostAgentEvent(
                    run_id=command.run_id,
                    sequence=sequence,
                    event=agent_event,
                )
                for widget_event in later_widgets:
                    sequence += 1
                    yield _widget_envelope(command.run_id, sequence, widget_event)

    async def _pending_widgets(
        self,
        run_id: UUID,
        emitted_count: int,
    ) -> tuple[WidgetEvent, ...]:
        if self._widget_events is None:
            return ()
        events = await self._widget_events.list_for_run(run_id)
        return events[emitted_count:]


def _widget_envelope(run_id: UUID, sequence: int, event: WidgetEvent) -> HostWidgetEvent:
    return HostWidgetEvent(run_id=run_id, sequence=sequence, event=event)


def _widget_occurred_at(event: WidgetEvent):
    return event.occurred_at
