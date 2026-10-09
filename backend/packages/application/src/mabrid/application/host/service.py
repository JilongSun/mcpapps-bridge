"""Merge owned domain events into one ordered Host presentation stream.

Each generator retains and joins its read tasks. Task-group cancellation scopes cannot safely
span yields when different consumer tasks may resume or close the same generator.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import aclosing
from uuid import UUID

import anyio

from ..agent_host import (
    AgentRunCompleted,
    AgentRunCancelled,
    AgentRunEvent,
    ToolActivityEvent,
    StartSessionRunCommand,
    RuntimeSessionRunStarted,
    RuntimeSessionTextDelta,
    RuntimeSessionRunCompleted,
    RuntimeSessionRunCancelled,
    AssistantTextDelta,
    AssistantTextCompleted,
    AgentRunResult,
    AgentRunFailed,
    AgentRunStarted,
    StartRunCommand,
    AgentRunSettlement,
    AgentSessionError,
)
from ..mcp_apps import WidgetEvent, WidgetCreated
from .contracts import HostAgentEvent, HostEvent, HostWidgetEvent, HostToolEvent
from .ports import AgentRunEventSource, WidgetEventReader, ToolActivityReader, SessionRunEventSource


class _HostEventMerger:
    def __init__(
        self,
        widget_events: WidgetEventReader | None = None,
        run_settlement: AgentRunSettlement | None = None,
        tool_activity: ToolActivityReader | None = None,
    ) -> None:
        self._widget_events = widget_events
        self._run_settlement = run_settlement
        self._tool_activity = tool_activity

    async def _merge(
        self, source: AsyncGenerator[AgentRunEvent, None], run_id: UUID
    ) -> AsyncGenerator[HostEvent, None]:
        sequence = 0
        emitted_widget_count = 0
        emitted_tool_count = 0
        agent_read: asyncio.Task[AgentRunEvent | None] | None = None
        widget_read: asyncio.Task[tuple[WidgetEvent, ...]] | None = None
        tool_read: asyncio.Task[tuple[ToolActivityEvent, ...]] | None = None
        try:
            first = await anext(source, None)
            if first is None:
                return
            sequence += 1
            yield HostAgentEvent(run_id=run_id, sequence=sequence, event=first)
            while True:
                if agent_read is None:
                    agent_read = asyncio.create_task(self._next_agent_event(source, run_id))
                if self._widget_events is not None and widget_read is None:
                    widget_read = asyncio.create_task(
                        self._widget_events.wait_for_events(run_id, emitted_widget_count)
                    )
                if self._tool_activity is not None and tool_read is None:
                    tool_read = asyncio.create_task(
                        self._tool_activity.wait_for_events(run_id, emitted_tool_count)
                    )
                reads: list[asyncio.Task[object]] = [agent_read]
                if widget_read is not None:
                    reads.append(widget_read)
                if tool_read is not None:
                    reads.append(tool_read)
                await asyncio.wait(reads, return_when=asyncio.FIRST_COMPLETED)

                if tool_read is not None and tool_read.done():
                    tool_read.result()
                    tool_read = None
                if self._tool_activity is not None:
                    for activity in (await self._tool_activity.list_for_run(run_id))[
                        emitted_tool_count:
                    ]:
                        emitted_tool_count += 1
                        sequence += 1
                        yield HostToolEvent(run_id=run_id, sequence=sequence, event=activity)
                if widget_read is not None and widget_read.done():
                    widgets = widget_read.result()
                    widget_read = None
                    emitted_widget_count += len(widgets)
                    for widget_event in widgets:
                        sequence += 1
                        yield await self._widget_envelope(run_id, sequence, widget_event)
                if not agent_read.done():
                    continue
                agent_event = agent_read.result()
                agent_read = None
                if agent_event is None:
                    return
                terminal = isinstance(
                    agent_event, (AgentRunCompleted, AgentRunFailed, AgentRunCancelled)
                )
                if terminal and self._widget_events is not None:
                    for widget_event in (await self._widget_events.list_for_run(run_id))[
                        emitted_widget_count:
                    ]:
                        sequence += 1
                        yield await self._widget_envelope(run_id, sequence, widget_event)
                sequence += 1
                yield HostAgentEvent(run_id=run_id, sequence=sequence, event=agent_event)
                if terminal:
                    return
        finally:
            with anyio.CancelScope(shield=True):
                reads = [read for read in (agent_read, widget_read, tool_read) if read is not None]
                for read in reads:
                    if not read.done():
                        read.cancel()
                outcomes = await asyncio.gather(*reads, return_exceptions=True)
                await source.aclose()
                for outcome in outcomes:
                    if isinstance(outcome, BaseException) and not isinstance(
                        outcome, asyncio.CancelledError
                    ):
                        raise outcome

    async def _next_agent_event(
        self, source: AsyncGenerator[AgentRunEvent, None], run_id: UUID
    ) -> AgentRunEvent | None:
        event = await anext(source, None)
        if isinstance(event, (AgentRunCompleted, AgentRunFailed, AgentRunCancelled)):
            if self._run_settlement is not None:
                try:
                    await self._run_settlement.wait_until_settled(run_id)
                except AgentSessionError:
                    if not isinstance(event, AgentRunFailed):
                        raise
            elif self._widget_events is not None:
                await self._widget_events.wait_until_settled(run_id)
        return event

    async def _widget_envelope(
        self, run_id: UUID, sequence: int, event: WidgetEvent
    ) -> HostWidgetEvent:
        invocation_id = None
        if self._tool_activity is not None:
            widget = event.widget if isinstance(event, WidgetCreated) else event
            invocation_id = await self._tool_activity.invocation_id(
                widget.session_key, widget.operation_key
            )
        return HostWidgetEvent(
            run_id=run_id, sequence=sequence, event=event, tool_invocation_id=invocation_id
        )


class HostEventStream(_HostEventMerger):
    def __init__(
        self,
        agent_runs: AgentRunEventSource,
        widget_events: WidgetEventReader | None = None,
        run_settlement: AgentRunSettlement | None = None,
        tool_activity: ToolActivityReader | None = None,
    ) -> None:
        super().__init__(widget_events, run_settlement, tool_activity)
        self._agent_runs = agent_runs

    async def run_events(self, command: StartRunCommand) -> AsyncGenerator[HostEvent, None]:
        async with aclosing(
            self._merge(self._agent_runs.run_events(command), command.run_id)
        ) as events:
            async for event in events:
                yield event


class HostSessionEventStream(_HostEventMerger):
    def __init__(
        self,
        session_runs: SessionRunEventSource,
        widget_events: WidgetEventReader | None = None,
        run_settlement: AgentRunSettlement | None = None,
        tool_activity: ToolActivityReader | None = None,
    ) -> None:
        super().__init__(widget_events, run_settlement, tool_activity)
        self._session_runs = session_runs

    async def run_events(self, command: StartSessionRunCommand) -> AsyncGenerator[HostEvent, None]:
        async with aclosing(self._merge(self._agent_events(command), command.run_id)) as events:
            async for event in events:
                yield event.model_copy(update={"session_id": command.session_id})

    async def _agent_events(
        self, command: StartSessionRunCommand
    ) -> AsyncGenerator[AgentRunEvent, None]:
        sequence = 0
        async with aclosing(self._session_runs.run_session(command)) as events:
            async for event in events:
                sequence += 1
                if isinstance(event, RuntimeSessionRunStarted):
                    yield AgentRunStarted(
                        run_id=command.run_id, sequence=sequence, model=self._session_runs.target_id
                    )
                elif isinstance(event, RuntimeSessionTextDelta):
                    yield AssistantTextDelta(
                        run_id=command.run_id, sequence=sequence, delta=event.delta
                    )
                elif isinstance(event, RuntimeSessionRunCompleted):
                    yield AssistantTextCompleted(
                        run_id=command.run_id, sequence=sequence, text=event.output_text
                    )
                    sequence += 1
                    yield AgentRunCompleted(
                        run_id=command.run_id,
                        sequence=sequence,
                        result=AgentRunResult(
                            run_id=command.run_id,
                            model=self._session_runs.target_id,
                            output_text=event.output_text,
                            usage=event.usage,
                        ),
                    )
                    return
                elif isinstance(event, RuntimeSessionRunCancelled):
                    yield AgentRunCancelled(run_id=command.run_id, sequence=sequence)
                    return
        raise AgentSessionError(
            "runtime_contract_error", "Runtime Run ended without a completion event"
        )
