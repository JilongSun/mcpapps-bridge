"""Provider-neutral Agent Host orchestration."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import aclosing

from ..contracts import (
    AgentAdapterCompleted,
    AgentAdapterTextDelta,
    AgentModel,
    AgentRunCompleted,
    AgentRunEvent,
    AgentRunFailed,
    AgentRunResult,
    AgentRunStarted,
    AgentRuntimeProfile,
    AgentTarget,
    AssistantTextCompleted,
    AssistantTextDelta,
    StartRunCommand,
)
from .coordination import AgentRunCoordinator
from .ports import AgentRuntime


class AgentRunError(RuntimeError):
    """Raised when a provider runtime cannot complete an agent run."""


class AgentHostService:
    def __init__(
        self,
        target: AgentTarget,
        runtime: AgentRuntime,
        coordinator: AgentRunCoordinator,
    ) -> None:
        if target.runtime_profile != runtime.profile:
            raise ValueError(
                f"Runtime profile {runtime.profile.interface!s} does not match Agent Target "
                f"profile {target.runtime_profile.interface!s}"
            )
        self._target = target
        self._runtime = runtime
        self._coordinator = coordinator
        if (
            self._coordinator.target_for_endpoint(target.endpoint_assignment.endpoint_slug)
            != target
        ):
            raise ValueError(
                f"Agent Target {target.target_id!r} is not registered with its Run coordinator"
            )

    @property
    def target(self) -> AgentTarget:
        return self._target

    @property
    def runtime_profile(self) -> AgentRuntimeProfile:
        return self._target.runtime_profile

    @property
    def coordinator(self) -> AgentRunCoordinator:
        return self._coordinator

    async def list_models(self) -> list[AgentModel]:
        return [
            AgentModel(
                model_id=self._target.target_id,
                owned_by=self._target.runtime_profile.integration_kind,
            )
        ]

    async def run_events(self, command: StartRunCommand) -> AsyncGenerator[AgentRunEvent, None]:
        command = command.model_copy(update={"model": self._target.target_id})
        await self._coordinator.start_run(self._target.target_id, command.run_id)
        run_active = True
        sequence = 1
        try:
            yield AgentRunStarted(
                run_id=command.run_id,
                sequence=sequence,
                model=command.model,
            )
            text_parts: list[str] = []
            async with aclosing(self._runtime.run(command)) as adapter_events:
                async for event in adapter_events:
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
        finally:
            if run_active:
                await self._coordinator.finish_run(self._target.target_id, command.run_id)

    async def complete(self, command: StartRunCommand) -> AgentRunResult:
        result: AgentRunResult | None = None
        failure: AgentRunFailed | None = None
        async for event in self.run_events(command):
            if isinstance(event, AgentRunCompleted):
                result = event.result
            if isinstance(event, AgentRunFailed):
                failure = event
        if result is not None:
            return result
        message = failure.error_message if failure is not None else "Agent run did not complete"
        raise AgentRunError(message)
