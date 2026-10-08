from __future__ import annotations

import json

import httpx
from mabrid.application.agent_host import (
    AgentAdapterCompleted,
    AgentAdapterTextDelta,
    AgentCapability,
    AgentMessage,
    AgentRuntimeInterface,
    StartRunCommand,
)
from mabrid.application.agent_host.integrations.hermes import (
    HermesCapabilityDocument,
    HermesChatCompletionsAdapter,
)
from openai import AsyncOpenAI
import pytest
from pydantic import ValidationError

from mabrid.application.agent_host.integrations.hermes.session_documents import (
    HermesHistoryDocument,
    HermesRunStatusDocument,
    HermesSessionChatRequest,
    HermesSessionCreateRequest,
    HermesSessionDocument,
    HermesStopDocument,
)


@pytest.fixture
def native_session_transport() -> httpx.MockTransport:
    run_status = "running"

    async def handle(request: httpx.Request) -> httpx.Response:
        nonlocal run_status
        if request.headers.get("authorization") != "Bearer fixture-key":
            return httpx.Response(401, json={"error": {"code": "unauthorized"}})
        if request.method == "POST" and request.url.path == "/api/sessions":
            payload = HermesSessionCreateRequest.model_validate_json(request.content)
            return httpx.Response(
                201,
                json={
                    "object": "hermes.session",
                    "session": {
                        "id": "api_fixture",
                        "title": payload.title,
                        "source": "api_server",
                    },
                },
            )
        if request.url.path == "/api/sessions/missing":
            return httpx.Response(404, json={"error": {"code": "session_not_found"}})
        if request.method == "GET" and request.url.path == "/api/sessions/api_fixture/messages":
            assert dict(request.url.params) == {"limit": "2", "offset": "0", "order": "latest"}
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "session_id": "api_fixture",
                    "data": [
                        {
                            "id": 1,
                            "role": "assistant",
                            "content": "Searching",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "fixture__search", "arguments": "{}"},
                                }
                            ],
                        },
                        {"id": 2, "role": "tool", "content": "Found", "tool_call_id": "call_1"},
                    ],
                    "pagination": {"limit": 2, "offset": 0, "order": "latest", "returned": 2},
                },
            )
        if request.method == "POST" and request.url.path == "/api/sessions/api_fixture/chat/stream":
            payload = HermesSessionChatRequest.model_validate_json(request.content)
            assert payload.message == "Continue"
            frames = [
                ("run.started", {"run_id": "run_fixture", "session_id": "api_fixture", "seq": 1}),
                ("assistant.delta", {"delta": "Hello", "run_id": "run_fixture", "seq": 2}),
                ("assistant.completed", {"content": "Hello", "completed": True, "seq": 3}),
                ("run.completed", {"completed": True, "session_id": "api_fixture", "seq": 4}),
                ("done", {"run_id": "run_fixture", "seq": 5}),
            ]
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream", "x-hermes-session-id": "api_fixture"},
                text="".join(
                    f"event: {name}\ndata: {json.dumps(payload)}\n\n" for name, payload in frames
                ),
            )
        if request.method == "POST" and request.url.path == "/v1/runs/run_fixture/stop":
            run_status = "stopping"
            return httpx.Response(200, json={"run_id": "run_fixture", "status": "stopping"})
        if request.method == "GET" and request.url.path == "/v1/runs/run_fixture":
            return httpx.Response(
                200,
                json={"run_id": "run_fixture", "status": run_status, "session_id": "api_fixture"},
            )
        raise AssertionError(
            f"Unexpected native Hermes fixture request: {request.method} {request.url}"
        )

    return httpx.MockTransport(handle)


async def test_native_session_wire_fixture_preserves_history_and_pending_stop(
    native_session_transport: httpx.MockTransport,
) -> None:
    async with httpx.AsyncClient(
        base_url="http://hermes.test",
        headers={"authorization": "Bearer fixture-key"},
        transport=native_session_transport,
    ) as client:
        created = await client.post("/api/sessions", json={"title": "Fixture"})
        session = HermesSessionDocument.model_validate(created.json())
        assert created.status_code == 201
        assert session.session.id == "api_fixture"

        response = await client.get(
            "/api/sessions/api_fixture/messages",
            params={"limit": 2, "offset": 0, "order": "latest"},
        )
        history = HermesHistoryDocument.model_validate(response.json())
        assert history.pagination.returned == 2
        assert history.data[0].tool_calls is not None
        assert history.data[0].tool_calls[0].id == history.data[1].tool_call_id
        assert "has_more" not in history.model_dump()

        streamed = await client.post(
            "/api/sessions/api_fixture/chat/stream", json={"message": "Continue"}
        )
        assert streamed.headers["x-hermes-session-id"] == "api_fixture"
        assert "event: run.started\n" in streamed.text
        assert "event: run.completed\n" in streamed.text
        assert "event: done\n" in streamed.text

        stopped = HermesStopDocument.model_validate(
            (await client.post("/v1/runs/run_fixture/stop")).json()
        )
        status = HermesRunStatusDocument.model_validate(
            (await client.get("/v1/runs/run_fixture")).json()
        )
        assert stopped.status == "stopping"
        assert status.status == "stopping"

        missing = await client.get("/api/sessions/missing")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "session_not_found"


def test_native_session_chat_request_cannot_replay_a_transcript() -> None:
    with pytest.raises(ValidationError):
        HermesSessionChatRequest.model_validate({"message": "Continue", "messages": []})


async def test_hermes_runtime_reads_its_typed_capabilities() -> None:
    requests: list[httpx.Request] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "object": "hermes.api_server.capabilities",
                "platform": "hermes-agent",
                "model": "hermes-agent",
                "auth": {"type": "bearer", "required": True},
                "runtime": {
                    "mode": "server_agent",
                    "tool_execution": "server",
                    "split_runtime": False,
                },
                "features": {
                    "chat_completions": True,
                    "chat_completions_streaming": True,
                    "responses_api": True,
                    "run_submission": True,
                    "run_stop": True,
                    "run_steer": True,
                    "run_approval_response": True,
                    "tool_progress_events": True,
                    "session_continuity_header": "X-Hermes-Session-Id",
                },
                "endpoints": {
                    "chat_completions": {
                        "method": "POST",
                        "path": "/v1/chat/completions",
                    },
                    "runs": {"method": "POST", "path": "/v1/runs"},
                },
            },
        )

    runtime = HermesChatCompletionsAdapter(
        base_url="http://unused.test/v1",
        api_key="unused",
        client=AsyncOpenAI(
            base_url="http://hermes.test/v1",
            api_key="fixture-key",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        ),
    )
    try:
        capabilities = await runtime.fetch_capability_document()
    finally:
        await runtime.close()

    assert isinstance(capabilities, HermesCapabilityDocument)
    assert capabilities.platform == "hermes-agent"
    assert capabilities.features.responses_api is True
    assert capabilities.features.session_continuity_header == "X-Hermes-Session-Id"
    assert capabilities.endpoints["runs"].path == "/v1/runs"
    assert [request.url.path for request in requests] == ["/v1/capabilities"]
    assert requests[0].headers["authorization"] == "Bearer fixture-key"


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

        def chunk(choices: list[dict[str, object]], usage: dict[str, int] | None = None) -> str:
            return (
                "data: "
                + json.dumps(
                    {
                        "id": "chatcmpl-hermes",
                        "object": "chat.completion.chunk",
                        "created": 1_700_000_001,
                        "model": "hermes-agent",
                        "choices": choices,
                        "usage": usage,
                    }
                )
                + "\n\n"
            )

        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                chunk(
                    [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": "Hello"},
                            "finish_reason": None,
                        }
                    ]
                )
                + chunk([{"index": 0, "delta": {"content": " from Hermes"}, "finish_reason": None}])
                + chunk([{"index": 0, "delta": {}, "finish_reason": "stop"}])
                + chunk([], {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7})
                + "data: [DONE]\n\n"
            ),
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    openai_client = AsyncOpenAI(
        base_url="http://hermes.test/v1",
        api_key="fixture-key",
        http_client=http_client,
    )
    runtime = HermesChatCompletionsAdapter(
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

    assert [event.kind for event in events] == [
        "adapter.text.delta",
        "adapter.text.delta",
        "adapter.completed",
    ]
    assert isinstance(events[0], AgentAdapterTextDelta)
    assert [event.delta for event in events if isinstance(event, AgentAdapterTextDelta)] == [
        "Hello",
        " from Hermes",
    ]
    assert isinstance(events[-1], AgentAdapterCompleted)
    assert events[-1].usage.total_tokens == 7
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
        "stream": True,
        "stream_options": {"include_usage": True},
    }


async def test_hermes_runtime_requires_exactly_one_remote_model() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"object": "list", "data": []})

    runtime = HermesChatCompletionsAdapter(
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


async def test_hermes_stream_accepts_explicit_empty_assistant_text() -> None:
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
            headers={"content-type": "text/event-stream"},
            text="data: "
            + json.dumps(
                {
                    "id": "chatcmpl-hermes",
                    "object": "chat.completion.chunk",
                    "created": 1_700_000_001,
                    "model": "hermes-agent",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": ""},
                            "finish_reason": "stop",
                        }
                    ],
                }
            )
            + "\n\ndata: [DONE]\n\n",
        )

    runtime = HermesChatCompletionsAdapter(
        base_url="http://unused.test/v1",
        api_key="unused",
        client=AsyncOpenAI(
            base_url="http://hermes.test/v1",
            api_key="fixture-key",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        ),
    )
    try:
        events = [
            event
            async for event in runtime.run(
                StartRunCommand(
                    model="fixture-target",
                    messages=(AgentMessage(role="user", content="Say hello"),),
                )
            )
        ]
    finally:
        await runtime.close()

    assert len(events) == 1
    assert isinstance(events[0], AgentAdapterCompleted)
    assert events[0].finish_reason == "stop"


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
            headers={"content-type": "text/event-stream"},
            text="".join(
                "data: "
                + json.dumps(
                    {
                        "id": "chatcmpl-hermes",
                        "object": "chat.completion.chunk",
                        "created": 1_700_000_001,
                        "model": "hermes-agent",
                        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
                    }
                )
                + "\n\n"
                for delta, finish_reason in [
                    ({"role": "assistant", "content": "Partial output"}, None),
                    ({}, "error"),
                ]
            )
            + "data: [DONE]\n\n",
        )

    openai_client = AsyncOpenAI(
        base_url="http://hermes.test/v1",
        api_key="fixture-key",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    runtime = HermesChatCompletionsAdapter(
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
