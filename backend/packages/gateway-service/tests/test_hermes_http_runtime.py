from __future__ import annotations

import json

import httpx
from mcp_gateway_service import (
    AgentAdapterCompleted,
    AgentAdapterTextDelta,
    AgentCapability,
    AgentMessage,
    AgentRuntimeInterface,
    StartRunCommand,
)
from mcp_gateway_service.agent_host.runtimes import HermesHttpAgentRuntime
from openai import AsyncOpenAI
import pytest


async def test_hermes_runtime_uses_official_openai_chat_contract() -> None:
    requests: list[httpx.Request] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {
                            "id": "hermes-agent",
                            "object": "model",
                            "created": 1_700_000_000,
                            "owned_by": "hermes",
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-hermes",
                "object": "chat.completion",
                "created": 1_700_000_001,
                "model": "fixture-target",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hello from Hermes"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 4,
                    "completion_tokens": 3,
                    "total_tokens": 7,
                },
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    openai_client = AsyncOpenAI(
        base_url="http://hermes.test/v1",
        api_key="fixture-key",
        http_client=http_client,
    )
    runtime = HermesHttpAgentRuntime(
        base_url="http://unused.test/v1",
        api_key="unused",
        client=openai_client,
    )
    try:
        assert runtime.profile.integration_kind == "hermes"
        assert runtime.profile.interface is AgentRuntimeInterface.OPENAI_CHAT_COMPLETIONS
        assert runtime.profile.capabilities == frozenset(
            {
                AgentCapability.TEXT_GENERATION,
                AgentCapability.TOKEN_USAGE,
            }
        )
        events = [
            event
            async for event in runtime.run(
                StartRunCommand(
                    model="fixture-target",
                    messages=(
                        AgentMessage(role="developer", content="Be concise"),
                        AgentMessage(role="user", content="Say hello"),
                    ),
                )
            )
        ]
    finally:
        await runtime.close()

    assert [event.kind for event in events] == ["adapter.text.delta", "adapter.completed"]
    assert isinstance(events[0], AgentAdapterTextDelta)
    assert events[0].delta == "Hello from Hermes"
    assert isinstance(events[1], AgentAdapterCompleted)
    assert events[1].usage.total_tokens == 7
    assert [request.url.path for request in requests] == [
        "/v1/models",
        "/v1/chat/completions",
    ]
    assert all(request.headers["authorization"] == "Bearer fixture-key" for request in requests)
    assert json.loads(requests[1].content) == {
        "messages": [
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": "Say hello"},
        ],
        "model": "hermes-agent",
        "stream": False,
    }


async def test_hermes_runtime_requires_exactly_one_remote_model() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"object": "list", "data": []})

    runtime = HermesHttpAgentRuntime(
        base_url="http://unused.test/v1",
        api_key="unused",
        client=AsyncOpenAI(
            base_url="http://hermes.test/v1",
            api_key="fixture-key",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        ),
    )
    try:
        events = runtime.run(
            StartRunCommand(
                model="fixture-target",
                messages=(AgentMessage(role="user", content="Say hello"),),
            )
        )
        with pytest.raises(RuntimeError, match="exactly one model, received 0"):
            await anext(events)
    finally:
        await runtime.close()


async def test_hermes_runtime_normalizes_nonstandard_error_finish_reason() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {
                            "id": "hermes-agent",
                            "object": "model",
                            "created": 1_700_000_000,
                            "owned_by": "hermes",
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-hermes",
                "object": "chat.completion",
                "created": 1_700_000_001,
                "model": "fixture-target",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Partial output"},
                        "finish_reason": "error",
                    }
                ],
            },
        )

    openai_client = AsyncOpenAI(
        base_url="http://hermes.test/v1",
        api_key="fixture-key",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    runtime = HermesHttpAgentRuntime(
        base_url="http://unused.test/v1",
        api_key="unused",
        client=openai_client,
    )
    try:
        events = runtime.run(
            StartRunCommand(
                model="fixture-target",
                messages=(AgentMessage(role="user", content="Say hello"),),
            )
        )
        first = await anext(events)
        assert isinstance(first, AgentAdapterTextDelta)
        assert first.delta == "Partial output"
        with pytest.raises(RuntimeError, match="finish reason: error"):
            await anext(events)
    finally:
        await runtime.close()
