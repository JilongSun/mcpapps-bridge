from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from mcp_gateway_service.agent_host import (
    AgentAdapterCompleted,
    AgentAdapterEvent,
    AgentAdapterTextDelta,
    AgentHostService,
    AgentMessage,
    AgentModel,
    AgentRunError,
    AgentRuntimeAdapter,
    StartRunCommand,
    TokenUsage,
)


class SuccessfulAdapter:
    async def list_models(self) -> list[AgentModel]:
        return [AgentModel(model_id="fixture-model", owned_by="fixture")]

    async def run(self, command: StartRunCommand) -> AsyncIterator[AgentAdapterEvent]:
        assert command.model == "fixture-model"
        yield AgentAdapterTextDelta(delta="Hello")
        yield AgentAdapterTextDelta(delta=" world")
        yield AgentAdapterCompleted(
            finish_reason="stop",
            usage=TokenUsage(input_tokens=3, output_tokens=2),
        )


class FailingAdapter:
    async def list_models(self) -> list[AgentModel]:
        return []

    async def run(self, command: StartRunCommand) -> AsyncIterator[AgentAdapterEvent]:
        raise RuntimeError(f"Provider unavailable for {command.model}")
        yield


def _command() -> StartRunCommand:
    return StartRunCommand(
        model="fixture-model",
        messages=(AgentMessage(role="user", content="Say hello"),),
    )


async def test_agent_host_emits_provider_neutral_ordered_events() -> None:
    service = AgentHostService(SuccessfulAdapter())

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
    assert completed.result.output_text == "Hello world"
    assert completed.result.usage.total_tokens == 5


async def test_agent_host_complete_returns_the_terminal_result() -> None:
    service = AgentHostService(SuccessfulAdapter())

    result = await service.complete(_command())

    assert result.output_text == "Hello world"
    assert result.finish_reason == "stop"


async def test_agent_host_normalizes_adapter_failure() -> None:
    adapter: AgentRuntimeAdapter = FailingAdapter()
    service = AgentHostService(adapter)

    events = [event async for event in service.run_events(_command())]

    assert [event.kind for event in events] == ["run.started", "run.failed"]
    assert events[-1].sequence == 2
    with pytest.raises(AgentRunError, match="Provider unavailable for fixture-model"):
        await service.complete(_command())
