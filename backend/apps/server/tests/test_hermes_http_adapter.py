from __future__ import annotations

import json

import httpx
from mcp_gateway_service import (
    AgentAdapterCompleted,
    AgentAdapterTextDelta,
    AgentMessage,
    StartRunCommand,
)
from openai import AsyncOpenAI
import pytest

from mcp_gateway_server.agent_adapters import HermesHttpAgentAdapter


async def test_hermes_adapter_uses_official_openai_models_and_chat_contract() -> None:
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
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-hermes",
                    "object": "chat.completion",
                    "created": 1_700_000_001,
                    "model": "hermes-agent",
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
        return httpx.Response(404)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    openai_client = AsyncOpenAI(
        base_url="http://hermes.test/v1",
        api_key="fixture-key",
        http_client=http_client,
    )
    adapter = HermesHttpAgentAdapter(
        base_url="http://unused.test/v1",
        api_key="unused",
        client=openai_client,
    )
    try:
        models = await adapter.list_models()
        events = [
            event
            async for event in adapter.run(
                StartRunCommand(
                    model="hermes-agent",
                    messages=(
                        AgentMessage(role="developer", content="Be concise"),
                        AgentMessage(role="user", content="Say hello"),
                    ),
                )
            )
        ]
    finally:
        await adapter.close()

    assert [(model.model_id, model.owned_by) for model in models] == [
        ("hermes-agent", "hermes")
    ]
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
    body = json.loads(requests[1].content)
    assert body == {
        "messages": [
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": "Say hello"},
        ],
        "model": "hermes-agent",
        "stream": False,
    }


async def test_hermes_adapter_normalizes_nonstandard_error_finish_reason() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-hermes",
                "object": "chat.completion",
                "created": 1_700_000_001,
                "model": "hermes-agent",
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
    adapter = HermesHttpAgentAdapter(
        base_url="http://unused.test/v1",
        api_key="unused",
        client=openai_client,
    )
    try:
        events = adapter.run(
            StartRunCommand(
                model="hermes-agent",
                messages=(AgentMessage(role="user", content="Say hello"),),
            )
        )
        first = await anext(events)
        assert isinstance(first, AgentAdapterTextDelta)
        assert first.delta == "Partial output"
        with pytest.raises(RuntimeError, match="finish reason: error"):
            await anext(events)
    finally:
        await adapter.close()