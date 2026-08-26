from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from mcp_gateway_service.agent_host import (
    AgentAdapterCompleted,
    AgentAdapterEvent,
    AgentAdapterTextDelta,
    AgentCapability,
    AgentEndpointAssignment,
    AgentHostService,
    AgentMessage,
    AgentRunError,
    AgentRuntime,
    AgentRuntimeInterface,
    AgentRuntimeProfile,
    AgentTarget,
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

    async def run(self, command: StartRunCommand) -> AsyncIterator[AgentAdapterEvent]:
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

    async def run(self, command: StartRunCommand) -> AsyncIterator[AgentAdapterEvent]:
        raise RuntimeError(f"Provider unavailable for {command.model}")
        yield


def _command() -> StartRunCommand:
    return StartRunCommand(
        model="caller-selected-model",
        messages=(AgentMessage(role="user", content="Say hello"),),
    )


async def test_agent_host_emits_provider_neutral_ordered_events() -> None:
    service = AgentHostService(TARGET, SuccessfulAdapter())

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
    service = AgentHostService(TARGET, SuccessfulAdapter())

    result = await service.complete(_command())

    assert result.output_text == "Hello world"
    assert result.finish_reason == "stop"


async def test_agent_host_normalizes_adapter_failure() -> None:
    adapter: AgentRuntime = FailingAdapter()
    service = AgentHostService(TARGET, adapter)

    events = [event async for event in service.run_events(_command())]

    assert [event.kind for event in events] == ["run.started", "run.failed"]
    assert events[-1].sequence == 2
    with pytest.raises(AgentRunError, match="Provider unavailable for fixture-target"):
        await service.complete(_command())


async def test_agent_host_advertises_only_its_canonical_target() -> None:
    service = AgentHostService(TARGET, SuccessfulAdapter())

    models = await service.list_models()

    assert [(model.model_id, model.owned_by) for model in models] == [("fixture-target", "fixture")]
    assert service.runtime_profile == PROFILE
    assert service.target.endpoint_assignment.endpoint_slug == "fixture-endpoint"


def test_agent_host_rejects_a_runtime_that_does_not_match_the_target() -> None:
    mismatched_profile = PROFILE.model_copy(
        update={"interface": AgentRuntimeInterface.OPENAI_RESPONSES}
    )

    class MismatchedRuntime(SuccessfulAdapter):
        @property
        def profile(self) -> AgentRuntimeProfile:
            return mismatched_profile

    with pytest.raises(ValueError, match="does not match Agent Target"):
        AgentHostService(TARGET, MismatchedRuntime())
