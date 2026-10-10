"""Public Host SSE projection and ownership of pre-admitted presentation streams."""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from uuid import UUID, uuid4

import anyio
from sse_starlette import EventSourceResponse
from sse_starlette.event import ServerSentEvent
from starlette.types import Scope, Receive, Send

from mabrid.application.agent_host import (
    AgentRunStarted,
    AgentRunCompleted,
    AgentRunCancelled,
    AgentRunFailed,
    AssistantTextDelta,
    AssistantTextCompleted,
    AgentSessionError,
    ToolInvocationStarted,
    ToolInvocationCompleted,
)
from mabrid.application.host import HostEvent, HostAgentEvent, HostToolEvent
from mabrid.application.mcp_apps import WidgetCreated

from .host_contracts import (
    HostStreamEvent,
    HostStreamPayload,
    HostRunStartedPayload,
    HostTextDeltaPayload,
    HostTextCompletedPayload,
    HostRunCompletedPayload,
    HostRunCancelledPayload,
    HostRunFailedPayload,
    HostToolStartedPayload,
    HostToolCompletedPayload,
    HostToolFailedPayload,
    HostWidgetCreatedPayload,
    HostWidgetFailedPayload,
    HostWidget,
    HostErrorResponse,
)


def project_host_event(envelope: HostEvent) -> HostStreamEvent:
    payload: HostStreamPayload
    if isinstance(envelope, HostAgentEvent):
        event = envelope.event
        if isinstance(event, AgentRunStarted):
            payload = HostRunStartedPayload(target_id=event.model)
        elif isinstance(event, AssistantTextDelta):
            payload = HostTextDeltaPayload(delta=event.delta)
        elif isinstance(event, AssistantTextCompleted):
            payload = HostTextCompletedPayload(text=event.text)
        elif isinstance(event, AgentRunCompleted):
            payload = HostRunCompletedPayload(
                output_text=event.result.output_text, usage=event.result.usage
            )
        elif isinstance(event, AgentRunCancelled):
            payload = HostRunCancelledPayload()
        elif isinstance(event, AgentRunFailed):
            payload = HostRunFailedPayload(
                error=HostErrorResponse(
                    code="runtime_unavailable",
                    message="The Agent runtime failed.",
                    session_id=envelope.session_id,
                    run_id=envelope.run_id,
                )
            )
        else:
            raise AgentSessionError(
                "runtime_contract_error", "Unsupported Agent presentation event"
            )
    elif isinstance(envelope, HostToolEvent):
        fields = envelope.event.model_dump(
            exclude={"event_id", "occurred_at", "run_id", "target_id"}
        )
        if isinstance(envelope.event, ToolInvocationStarted):
            payload = HostToolStartedPayload.model_validate(fields)
        elif isinstance(envelope.event, ToolInvocationCompleted):
            payload = HostToolCompletedPayload.model_validate(fields)
        else:
            payload = HostToolFailedPayload.model_validate(
                {**fields, "error_message": "Tool invocation failed."}
            )
    elif isinstance(envelope.event, WidgetCreated):
        widget = envelope.event.widget
        public = HostWidget.model_validate(
            {
                "widget_id": widget.widget_id,
                "tool_invocation_id": envelope.tool_invocation_id,
                "tool_name": widget.tool_name,
                "tool_result": widget.tool_result.model_dump(),
                "application_resource_uri": widget.application_resource_uri,
                "resource_contents": [content.model_dump() for content in widget.resource_contents],
                "resource_metadata": widget.resource_metadata,
            }
        )
        payload = HostWidgetCreatedPayload(widget=public)
    else:
        payload = HostWidgetFailedPayload.model_validate(
            {
                "tool_invocation_id": envelope.tool_invocation_id,
                "tool_name": envelope.event.tool_name,
                "tool_result": envelope.event.tool_result.model_dump(),
                "application_resource_uri": envelope.event.application_resource_uri,
                "error_message": "Widget resource is unavailable.",
            }
        )
    return HostStreamEvent.model_validate(
        {
            "event_id": envelope.event_id,
            "session_id": envelope.session_id,
            "run_id": envelope.run_id,
            "sequence": envelope.sequence,
            "created_at": envelope.created_at,
            "event": payload,
        }
    )


async def close_presentation(source: AsyncGenerator[HostEvent, None]) -> AgentSessionError | None:
    with anyio.CancelScope(shield=True):
        try:
            await source.aclose()
        except AgentSessionError as exc:
            return exc
        except Exception:
            return AgentSessionError("runtime_contract_error", "Presentation cleanup failed")
    return None


class HostEventSourceResponse(EventSourceResponse):
    media_type = "text/event-stream"

    def __init__(
        self,
        source: AsyncGenerator[HostEvent, None],
        first: HostEvent,
        session_id: UUID,
        run_id: UUID,
    ) -> None:
        self._source = source
        super().__init__(
            self._events(first, session_id, run_id),
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
            send_timeout=5.0,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await close_presentation(self._source)

    async def _events(
        self, first: HostEvent, session_id: UUID, run_id: UUID
    ) -> AsyncGenerator[ServerSentEvent, None]:
        sequence = 0
        failure: AgentSessionError | None = None
        try:
            current: HostEvent | None = first
            while current is not None:
                public = project_host_event(current)
                terminal = public.event.kind in {"run.completed", "run.failed", "run.cancelled"}
                if terminal:
                    cleanup_error = await close_presentation(self._source)
                    if cleanup_error is not None:
                        raise cleanup_error
                sequence = public.sequence
                yield ServerSentEvent(
                    event=public.event.kind, data=public.model_dump_json(), id=str(public.event_id)
                )
                if terminal:
                    return
                current = await anext(self._source, None)
            failure = AgentSessionError(
                "runtime_contract_error", "Presentation ended without a terminal event"
            )
        except AgentSessionError as exc:
            failure = exc
        except Exception:
            failure = AgentSessionError("runtime_contract_error", "Presentation failed")
        finally:
            cleanup_error = await close_presentation(self._source)
            if cleanup_error is not None:
                failure = cleanup_error
        if failure is not None:
            from .host import host_error

            public = HostStreamEvent(
                event_id=uuid4(),
                session_id=session_id,
                run_id=run_id,
                sequence=sequence + 1,
                created_at=datetime.now(timezone.utc),
                event=HostRunFailedPayload(
                    error=host_error(failure.code, session_id=session_id, run_id=run_id)
                ),
            )
            yield ServerSentEvent(
                event="run.failed", data=public.model_dump_json(), id=str(public.event_id)
            )
