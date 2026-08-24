"""Provider-neutral Agent Host orchestration."""

from __future__ import annotations

from collections.abc import AsyncIterator

from .events import (
    AgentAdapterCompleted,
    AgentAdapterTextDelta,
    AgentRunCompleted,
    AgentRunEvent,
    AgentRunFailed,
    AgentRunStarted,
    AssistantTextCompleted,
    AssistantTextDelta,
)
from .models import AgentModel, AgentRunResult, StartRunCommand
from .ports import AgentRuntimeAdapter


class AgentRunError(RuntimeError):
    """Raised when a provider runtime cannot complete an agent run."""


class AgentHostService:
    def __init__(self, adapter: AgentRuntimeAdapter) -> None:
        self._adapter = adapter

    async def list_models(self) -> list[AgentModel]:
        return await self._adapter.list_models()

    async def run_events(self, command: StartRunCommand) -> AsyncIterator[AgentRunEvent]:
        sequence = 1
        yield AgentRunStarted(
            run_id=command.run_id,
            sequence=sequence,
            model=command.model,
        )
        text_parts: list[str] = []
        try:
            async for event in self._adapter.run(command):
                sequence += 1
                if isinstance(event, AgentAdapterTextDelta):
                    text_parts.append(event.delta)
                    yield AssistantTextDelta(
                        run_id=command.run_id,
                        sequence=sequence,
                        delta=event.delta,
                    )
                    continue
                if isinstance(event, AgentAdapterCompleted):
                    text = "".join(text_parts)
                    yield AssistantTextCompleted(
                        run_id=command.run_id,
                        sequence=sequence,
                        text=text,
                    )
                    sequence += 1
                    yield AgentRunCompleted(
                        run_id=command.run_id,
                        sequence=sequence,
                        result=AgentRunResult(
                            run_id=command.run_id,
                            model=command.model,
                            output_text=text,
                            finish_reason=event.finish_reason,
                            usage=event.usage,
                        ),
                    )
                    return
            raise AgentRunError("Agent runtime ended without a completion event")
        except Exception as exc:
            sequence += 1
            yield AgentRunFailed(
                run_id=command.run_id,
                sequence=sequence,
                error_message=str(exc),
            )

    async def complete(self, command: StartRunCommand) -> AgentRunResult:
        failure: AgentRunFailed | None = None
        async for event in self.run_events(command):
            if isinstance(event, AgentRunCompleted):
                return event.result
            if isinstance(event, AgentRunFailed):
                failure = event
        message = failure.error_message if failure is not None else "Agent run did not complete"
        raise AgentRunError(message)
