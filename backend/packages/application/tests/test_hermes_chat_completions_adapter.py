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
from mabrid.application.agent_host.integrations.hermes.sessions import HermesSessionAdapter
from mabrid.application.agent_host import (
    CreateAgentSessionCommand,
    HistoryPageQuery,
    RuntimeSessionReference,
)
from mabrid.application.agent_host.application.session_errors import AgentSessionError


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
                    f"event: {name}\ndata: {json.dumps({'run_id': 'run_fixture', 'session_id': 'api_fixture', **payload})}\n\n"
                    for name, payload in frames
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


@pytest.mark.parametrize("interface", ["native", "compatibility"])
@pytest.mark.parametrize(
    "mode",
    [
        "verified",
        "omitted",
        "false",
        "wrong_endpoint",
        "invalid",
        "invalid_boolean",
        "unauthorized",
        "outage",
        "missing",
    ],
)
async def test_runtime_discovery_is_read_only_and_keeps_unknown_support(
    interface: str, mode: str
) -> None:
    requests: list[httpx.Request] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET" and request.url.path == "/proxy/hermes/v1/capabilities"
        assert request.headers["authorization"] == "Bearer fixture-key"
        if mode in {"unauthorized", "outage", "missing"}:
            return httpx.Response(
                {"unauthorized": 401, "outage": 503, "missing": 404}[mode], text="private-secret"
            )
        features = {
            "session_resources": True,
            "session_chat_streaming": True,
            "run_status": True,
            "run_stop": True,
            "chat_completions_streaming": True,
        }
        if mode == "omitted":
            features = {}
        elif mode == "false":
            features = dict.fromkeys(features, False)
        document = {
            "object": "wrong" if mode == "invalid" else "hermes.api_server.capabilities",
            "platform": "hermes-agent",
            "model": "private-model",
            "auth": {"type": "bearer", "required": True},
            "runtime": {"mode": "server_agent", "tool_execution": "server", "split_runtime": False},
            "features": features,
            "endpoints": {
                name: {"method": method, "path": path}
                for name, method, path in (
                    ("session_create", "POST", "/api/sessions"),
                    ("session", "GET", "/api/sessions/{session_id}"),
                    ("session_messages", "GET", "/api/sessions/{session_id}/messages"),
                    ("session_chat_stream", "POST", "/api/sessions/{session_id}/chat/stream"),
                    ("run_status", "GET", "/v1/runs/{run_id}"),
                    ("run_stop", "POST", "/v1/runs/{run_id}/stop"),
                    ("chat_completions", "POST", "/v1/chat/completions"),
                )
            },
        }
        if mode == "wrong_endpoint":
            document["endpoints"] = {}
        if mode == "invalid_boolean":
            document["features"] = {"run_stop": "true"}
        return httpx.Response(200, json=document)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter = (
        HermesSessionAdapter(
            api_root="http://hermes.test/proxy/hermes",
            api_key="fixture-key",
            runtime_binding_id="fixture",
            client=client,
        )
        if interface == "native"
        else HermesChatCompletionsAdapter(
            base_url="http://hermes.test/proxy/hermes/v1",
            api_key="fixture-key",
            client=AsyncOpenAI(
                base_url="http://hermes.test/proxy/hermes/v1",
                api_key="fixture-key",
                http_client=client,
                max_retries=0,
            ),
        )
    )
    try:
        observation = await adapter.inspect_capabilities()
        assert len(requests) == 1
        if mode in {"verified", "omitted", "false", "wrong_endpoint"}:
            assert observation.availability == "available"
            expected = True if mode == "verified" else False if mode == "false" else None
            assert all(value is expected for value in observation.support.model_dump().values())
        else:
            assert observation.availability == (
                "unavailable" if mode in {"unauthorized", "outage"} else "unknown"
            )
            assert all(value is None for value in observation.support.model_dump().values())
        assert (
            "private-secret" not in observation.model_dump_json()
            and "private-model" not in observation.model_dump_json()
        )
    finally:
        await adapter.close()


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


async def test_native_adapter_reads_runtime_history_without_replaying_it(
    native_session_transport: httpx.MockTransport,
) -> None:
    adapter = HermesSessionAdapter(
        api_root="http://hermes.test/",
        api_key="fixture-key",
        runtime_binding_id="fixture-deployment",
        client=httpx.AsyncClient(transport=native_session_transport),
    )
    try:
        remote = await adapter.create_session(CreateAgentSessionCommand(title="Fixture"))
        reference = RuntimeSessionReference(
            runtime_binding_id="fixture-deployment", remote_session_id=remote.remote_session_id
        )
        history = await adapter.read_history(reference, HistoryPageQuery(limit=2))
        assert history.has_more is None
        assert history.messages[0].content[1].kind == "tool_call"
        assert history.messages[1].tool_call_id == "call_1"
        with pytest.raises(AgentSessionError) as missing:
            await adapter.get_session(reference.model_copy(update={"remote_session_id": "missing"}))
        assert missing.value.code == "remote_session_not_found"
        with pytest.raises(AgentSessionError) as changed:
            await adapter.get_session(reference.model_copy(update={"runtime_binding_id": "other"}))
        assert changed.value.code == "runtime_binding_changed"
    finally:
        await adapter.close()


async def test_native_adapter_preserves_reverse_proxy_prefix() -> None:
    requests: list[httpx.Request] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, json={"object": "hermes.session", "session": {"id": "api_fixture"}}
        )

    adapter = HermesSessionAdapter(
        api_root="http://hermes.test/proxy/hermes/",
        api_key="fixture-key",
        runtime_binding_id="fixture-deployment",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    try:
        await adapter.get_session(
            RuntimeSessionReference(
                runtime_binding_id="fixture-deployment", remote_session_id="api_fixture"
            )
        )
    finally:
        await adapter.close()
    assert requests[0].url.path == "/proxy/hermes/api/sessions/api_fixture"


async def test_native_adapter_executes_new_input_and_terminal_usage(
    native_session_transport: httpx.MockTransport,
) -> None:
    from mabrid.application.agent_host import StartSessionRunCommand
    from uuid import uuid4

    adapter = HermesSessionAdapter(
        api_root="http://hermes.test/",
        api_key="fixture-key",
        runtime_binding_id="fixture-deployment",
        client=httpx.AsyncClient(transport=native_session_transport),
    )
    try:
        events = [
            event
            async for event in adapter.run_session(
                RuntimeSessionReference(
                    runtime_binding_id="fixture-deployment", remote_session_id="api_fixture"
                ),
                StartSessionRunCommand(session_id=uuid4(), input_text="Continue"),
            )
        ]
        assert [event.kind for event in events] == [
            "session_adapter.started",
            "session_adapter.text.delta",
            "session_adapter.completed",
        ]
        assert events[-1].kind == "session_adapter.completed"
        assert events[-1].output_text == "Hello"
    finally:
        await adapter.close()


@pytest.mark.parametrize("terminal", [True, False])
async def test_native_adapter_close_waits_for_remote_terminal(terminal: bool) -> None:
    from mabrid.application.agent_host import StartSessionRunCommand
    from uuid import uuid4

    requests: list[str] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path.endswith("/chat/stream"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text='event: run.started\ndata: {"run_id":"run_fixture","session_id":"api_fixture","seq":1}\n\n',
            )
        if request.url.path.endswith("/stop"):
            return httpx.Response(200, json={"run_id": "run_fixture", "status": "stopping"})
        return httpx.Response(
            200, json={"run_id": "run_fixture", "status": "cancelled" if terminal else "stopping"}
        )

    adapter = HermesSessionAdapter(
        api_root="http://hermes.test/",
        api_key="fixture-key",
        runtime_binding_id="fixture-deployment",
        settlement_timeout_seconds=0.02,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    stream = adapter.run_session(
        RuntimeSessionReference(
            runtime_binding_id="fixture-deployment", remote_session_id="api_fixture"
        ),
        StartSessionRunCommand(session_id=uuid4(), input_text="Continue"),
    )
    try:
        await anext(stream)
        if terminal:
            await stream.aclose()
        else:
            with pytest.raises(AgentSessionError) as unknown:
                await stream.aclose()
            assert unknown.value.code == "run_state_unknown"
        assert "/v1/runs/run_fixture/stop" in requests
        assert "/v1/runs/run_fixture" in requests
    finally:
        await adapter.close()


@pytest.mark.parametrize("started", [True, False])
async def test_native_done_without_completion_is_not_success(started: bool) -> None:
    from mabrid.application.agent_host import StartSessionRunCommand
    from uuid import uuid4

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/stream"):
            data = '{"run_id":"run_fixture","session_id":"api_fixture","seq":1}'
            text = (
                f"event: run.started\ndata: {data}\n\n" if started else ""
            ) + f"event: done\ndata: {data}\n\n"
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=text)
        return httpx.Response(
            200,
            json={
                "run_id": "run_fixture",
                "status": "stopping" if request.url.path.endswith("/stop") else "failed",
            },
        )

    adapter = HermesSessionAdapter(
        api_root="http://hermes.test/",
        api_key="fixture-key",
        runtime_binding_id="fixture-deployment",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    try:
        with pytest.raises(AgentSessionError) as failure:
            async for _event in adapter.run_session(
                RuntimeSessionReference(
                    runtime_binding_id="fixture-deployment", remote_session_id="api_fixture"
                ),
                StartSessionRunCommand(session_id=uuid4(), input_text="Continue"),
            ):
                pass
        assert failure.value.code == ("runtime_contract_error" if started else "run_state_unknown")
    finally:
        await adapter.close()


async def test_native_submission_timeout_has_unknown_remote_outcome() -> None:
    from mabrid.application.agent_host import StartSessionRunCommand
    from uuid import uuid4

    async def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("fixture timeout", request=request)

    adapter = HermesSessionAdapter(
        api_root="http://hermes.test/",
        api_key="fixture-key",
        runtime_binding_id="fixture-deployment",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    try:
        with pytest.raises(AgentSessionError) as unknown:
            await anext(
                adapter.run_session(
                    RuntimeSessionReference(
                        runtime_binding_id="fixture-deployment", remote_session_id="api_fixture"
                    ),
                    StartSessionRunCommand(session_id=uuid4(), input_text="Continue"),
                )
            )
        assert unknown.value.code == "run_state_unknown"
    finally:
        await adapter.close()


async def test_native_submission_cancellation_has_unknown_remote_outcome() -> None:
    import asyncio
    from mabrid.application.agent_host import StartSessionRunCommand
    from uuid import uuid4

    async def handle(request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError()

    adapter = HermesSessionAdapter(
        api_root="http://hermes.test/",
        api_key="fixture-key",
        runtime_binding_id="fixture-deployment",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    try:
        with pytest.raises(AgentSessionError) as unknown:
            await anext(
                adapter.run_session(
                    RuntimeSessionReference(
                        runtime_binding_id="fixture-deployment", remote_session_id="api_fixture"
                    ),
                    StartSessionRunCommand(session_id=uuid4(), input_text="Continue"),
                )
            )
        assert unknown.value.code == "run_state_unknown"
    finally:
        await adapter.close()


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
