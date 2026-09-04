from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

import httpx
import pytest
from mabrid.application.agent_host import (
    AgentAdapterCompleted,
    AgentAdapterEvent,
    AgentAdapterTextDelta,
    AgentCapability,
    AgentEndpointAssignment,
    AgentHostService,
    AgentRuntime,
    AgentRuntimeInterface,
    AgentRuntimeProfile,
    AgentTarget,
    StartRunCommand,
    TokenUsage,
)
from mabrid.application.gateway.sessions import GatewaySessionCoordinator
from openai import AsyncOpenAI
from openai import APIStatusError

from mabrid.server.api import create_app

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


class FixtureAgentAdapter:
    @property
    def profile(self) -> AgentRuntimeProfile:
        return PROFILE

    async def run(self, command: StartRunCommand) -> AsyncIterator[AgentAdapterEvent]:
        assert command.model == TARGET.target_id
        assert command.messages[-1].content == "Say hello"
        yield AgentAdapterTextDelta(delta="Hello")
        yield AgentAdapterTextDelta(delta=" from the fixture")
        yield AgentAdapterCompleted(
            usage=TokenUsage(input_tokens=2, output_tokens=4),
        )


class FailingAgentAdapter(FixtureAgentAdapter):
    async def run(self, command: StartRunCommand) -> AsyncIterator[AgentAdapterEvent]:
        raise RuntimeError(f"Provider unavailable for {command.model}")
        yield


def _openai_client(agent_host: AgentHostService) -> AsyncOpenAI:
    app = create_app(cast(GatewaySessionCoordinator, object()), agent_host=agent_host)
    http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )
    return AsyncOpenAI(
        api_key="test-key",
        base_url="http://test/v1",
        http_client=http_client,
    )


def _agent_host(runtime: AgentRuntime | None = None) -> AgentHostService:
    return AgentHostService(TARGET, runtime or FixtureAgentAdapter())


def test_chat_completions_openapi_describes_the_official_sdk_request_body() -> None:
    app = create_app(cast(GatewaySessionCoordinator, object()), agent_host=_agent_host())

    assert app.title == "Mabrid"
    operation = app.openapi()["paths"]["/v1/chat/completions"]["post"]
    request_body = operation["requestBody"]
    json_body = request_body["content"]["application/json"]
    schema = json_body["schema"]
    components = app.openapi()["components"]["schemas"]

    assert request_body["required"] is True
    assert schema["anyOf"] == [
        {"$ref": "#/components/schemas/CompletionCreateParamsNonStreaming"},
        {"$ref": "#/components/schemas/CompletionCreateParamsStreaming"},
    ]
    assert {"model", "messages"} <= set(
        components["CompletionCreateParamsNonStreaming"]["properties"]
    )
    assert json_body["examples"]["basic"]["value"] == {
        "model": "fixture-target",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": False,
    }


async def test_official_openai_client_lists_agent_models() -> None:
    async with _openai_client(_agent_host()) as client:
        models = await client.models.list()

    assert [(model.id, model.owned_by) for model in models.data] == [("fixture-target", "fixture")]


async def test_official_openai_client_creates_non_streaming_chat_completion() -> None:
    async with _openai_client(_agent_host()) as client:
        completion = await client.chat.completions.create(
            model="caller-model",
            messages=[{"role": "user", "content": "Say hello"}],
        )

    assert completion.object == "chat.completion"
    assert completion.model == "fixture-target"
    assert completion.choices[0].message.content == "Hello from the fixture"
    assert completion.usage is not None
    assert completion.usage.total_tokens == 6


async def test_openai_routes_are_absent_when_agent_host_is_not_composed() -> None:
    app = create_app(cast(GatewaySessionCoordinator, object()))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/v1/models")

    assert response.status_code == 404


async def test_official_openai_client_receives_provider_failure() -> None:
    async with _openai_client(_agent_host(FailingAgentAdapter())) as client:
        with pytest.raises(
            APIStatusError, match="Provider unavailable for fixture-target"
        ) as error:
            await client.chat.completions.create(
                model="fixture-model",
                messages=[{"role": "user", "content": "Say hello"}],
            )

    assert error.value.status_code == 502


async def test_openai_api_rejects_tool_messages_until_tool_events_are_supported() -> None:
    async with _openai_client(_agent_host()) as client:
        with pytest.raises(APIStatusError, match="Tool messages are not supported") as error:
            await client.chat.completions.create(
                model="fixture-model",
                messages=[
                    {
                        "role": "tool",
                        "content": "Tool result",
                        "tool_call_id": "call_fixture",
                    }
                ],
            )

    assert error.value.status_code == 422
