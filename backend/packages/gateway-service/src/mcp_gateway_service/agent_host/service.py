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
from .models import AgentModel, AgentRunResult, AgentRuntimeProfile, AgentTarget, StartRunCommand
from .ports import AgentRuntime


class AgentRunError(RuntimeError):
    """Raised when a provider runtime cannot complete an agent run."""


class AgentHostService:
    def __init__(self, target: AgentTarget, runtime: AgentRuntime) -> None:
        if target.runtime_profile != runtime.profile:
            raise ValueError(
                f"Runtime profile {runtime.profile.interface!s} does not match Agent Target "
                f"profile {target.runtime_profile.interface!s}"
            )
        self._target = target
        self._runtime = runtime

    @property
    def target(self) -> AgentTarget:
        return self._target

    @property
    def runtime_profile(self) -> AgentRuntimeProfile:
        return self._target.runtime_profile

    async def list_models(self) -> list[AgentModel]:
        return [
            AgentModel(
                model_id=self._target.target_id,
                owned_by=self._target.runtime_profile.integration_kind,
            )
        ]

    async def run_events(self, command: StartRunCommand) -> AsyncIterator[AgentRunEvent]:
        command = command.model_copy(update={"model": self._target.target_id})
        sequence = 1
        yield AgentRunStarted(
            run_id=command.run_id,
            sequence=sequence,
            model=command.model,
        )
        text_parts: list[str] = []
        try:
            async for event in self._runtime.run(command):
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
