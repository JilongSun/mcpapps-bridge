from __future__ import annotations

from collections.abc import AsyncGenerator
import json
from datetime import datetime, timezone
from typing import cast
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from mabrid.application.agent_host import (
    AgentAdapterCompleted,
    AgentAdapterEvent,
    AgentAdapterTextDelta,
    AgentCapability,
    AgentEndpointAssignment,
    AgentHostService,
    AgentRunCoordinator,
    AgentRuntime,
    AgentRuntimeInterface,
    AgentRuntimeProfile,
    AgentTarget,
    StartRunCommand,
    TokenUsage,
)
from mabrid.application.gateway.sessions import GatewaySessionCoordinator
from mabrid.application.host import HostEventStream
from openai import AsyncOpenAI
from openai import APIStatusError

from mabrid.server.api import create_app
from mabrid.server.api.host_contracts import (
    CreateHostSessionRequest,
    HostSessionPageResponse,
    HostSessionResponse,
    StartHostSessionRunRequest,
)
from mabrid.server.api.openai_compat import _stream_chat_completion
from mabrid.application.agent_host import AgentMessage
from mabrid.application.agent_host import InMemoryToolActivityStore, OperationRunAttribution
from mabrid.application.agent_host import ToolInvocationFailed
from mabrid.application.host import HostWidgetEvent, HostToolEvent
from mabrid.application.mcp_apps import (
    WidgetCreated,
    WidgetFailed,
    WidgetInstance,
    WidgetToolResult,
    ApplicationResourceContent,
)
from mabrid.server.api.host_stream import project_host_event
from mabrid.server.api.host_contracts import HostStreamEvent
from mabrid.bridge import ToolCallStarted, ToolCallCompleted, ToolCallResult


def test_first_party_session_schema_hides_runtime_and_transport_identifiers() -> None:
    session = HostSessionResponse(
        session_id=uuid4(),
        target_id="fixture-target",
        created_at=datetime.now(timezone.utc),
        binding_state="unknown",
    )
    page = HostSessionPageResponse(sessions=(session,), limit=20, offset=0, has_more=False)
    assert HostSessionPageResponse.model_validate_json(page.model_dump_json()) == page
    schema = json.dumps(HostSessionPageResponse.model_json_schema())
    for private_field in ("remote_session_id", "remote_run_id", "session_key", "operation_key"):
        assert private_field not in schema
        with pytest.raises(ValidationError):
            HostSessionResponse.model_validate({**session.model_dump(), private_field: "private"})


def test_first_party_run_schema_accepts_only_new_input() -> None:
    request = StartHostSessionRunRequest(input_text="Continue")
    assert request.model_dump() == {"input_text": "Continue"}
    with pytest.raises(ValidationError):
        StartHostSessionRunRequest.model_validate({"input_text": "Continue", "messages": []})
    with pytest.raises(ValidationError):
        CreateHostSessionRequest.model_validate({"title": "Fixture", "model": "remote-model"})


def test_public_host_widget_payload_keeps_resources_and_hides_routing_and_debug_errors() -> None:
    session_id, run_id, invocation_id = uuid4(), uuid4(), uuid4()
    tool_result = WidgetToolResult(
        content=({"type": "text", "text": "Tool result"},),
        structured_content={"value": 42},
        metadata={"fixture": True},
    )
    widget = WidgetInstance(
        run_id=run_id,
        target_id="fixture",
        session_key="private-session-key",
        operation_key="private-operation-key",
        tool_name="inspect",
        tool_result=tool_result,
        application_resource_uri="ui://fixture/inspect",
        resource_contents=(
            ApplicationResourceContent(
                uri="ui://fixture/inspect",
                mime_type="text/html;profile=mcp-app",
                text="<p>fixture</p>",
                metadata={"ui": {"csp": {"connectDomains": []}}},
            ),
        ),
        resource_metadata={"fixture": True},
    )
    created = project_host_event(
        HostWidgetEvent(
            run_id=run_id,
            session_id=session_id,
            sequence=1,
            tool_invocation_id=invocation_id,
            event=WidgetCreated(widget=widget),
        )
    )
    assert created.event.kind == "widget.created"
    assert created.event.widget.tool_invocation_id == invocation_id
    assert created.event.widget.resource_contents[0].text == "<p>fixture</p>"
    assert created.event.widget.resource_contents[0].metadata == {
        "ui": {"csp": {"connectDomains": []}}
    }
    assert created.event.widget.resource_contents[0].mime_type == "text/html;profile=mcp-app"
    assert created.event.widget.tool_result.structured_content == {"value": 42}
    failed = project_host_event(
        HostWidgetEvent(
            run_id=run_id,
            session_id=session_id,
            sequence=2,
            tool_invocation_id=invocation_id,
            event=WidgetFailed(
                run_id=run_id,
                target_id="fixture",
                session_key="private-session-key",
                operation_key="private-operation-key",
                tool_name="inspect",
                tool_result=tool_result,
                application_resource_uri="ui://fixture/inspect",
                error_message="private-runtime-url-and-secret",
            ),
        )
    )
    assert failed.event.kind == "widget.failed"
    assert failed.event.tool_result.structured_content == {"value": 42}
    tool_failed = project_host_event(
        HostToolEvent(
            run_id=run_id,
            session_id=session_id,
            sequence=3,
            event=ToolInvocationFailed(
                run_id=run_id,
                target_id="fixture",
                tool_invocation_id=invocation_id,
                tool_name="inspect",
                error_code="upstream_transport",
                error_message="private-runtime-url-and-secret",
            ),
        )
    )
    for event in (created, failed, tool_failed):
        assert HostStreamEvent.model_validate_json(event.model_dump_json()) == event
        assert event.session_id == session_id and event.run_id == run_id
        for private in (
            "session_key",
            "operation_key",
            "private-session-key",
            "private-operation-key",
            "private-runtime-url-and-secret",
        ):
            assert private not in event.model_dump_json()
    schema = json.dumps(HostStreamEvent.model_json_schema())
    for private_field in ("session_key", "operation_key", "remote_run_id", "runtime_binding_id"):
        assert private_field not in schema


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


async def test_openai_stream_filters_live_tool_activity() -> None:
    activity = InMemoryToolActivityStore()

    class ActivityAdapter(FixtureAgentAdapter):
        async def run(self, command: StartRunCommand) -> AsyncGenerator[AgentAdapterEvent, None]:
            await activity.record_started(
                OperationRunAttribution(
                    run_id=command.run_id,
                    target_id=TARGET.target_id,
                    session_key="session",
                    operation_key="operation",
                ),
                ToolCallStarted(
                    session_key="session",
                    operation_key="operation",
                    tool_name="activity-only-marker",
                    arguments={"value": 42},
                ),
            )
            async for event in super().run(command):
                if isinstance(event, AgentAdapterCompleted):
                    await activity.record_completed(
                        ToolCallCompleted(
                            session_key="session",
                            operation_key="operation",
                            result=ToolCallResult(structured_content={"activity_only_output": 42}),
                        )
                    )
                yield event

    coordinator = AgentRunCoordinator((TARGET,))
    source = AgentHostService(TARGET, ActivityAdapter(), coordinator)
    command = StartRunCommand(
        model=TARGET.target_id, messages=(AgentMessage(role="user", content="Say hello"),)
    )
    chunks = [
        chunk
        async for chunk in _stream_chat_completion(
            HostEventStream(source, tool_activity=activity),
            command,
            model=TARGET.target_id,
            include_usage=False,
        )
    ]
    assert len(await activity.list_for_run(command.run_id)) == 2
    assert chunks[-1] == "data: [DONE]\n\n"
    wire = "".join(chunks)
    for private_value in (
        "host.tool",
        "tool_invocation_id",
        "activity-only-marker",
        "activity_only_output",
    ):
        assert private_value not in wire
    documents = [json.loads(chunk.removeprefix("data: ").strip()) for chunk in chunks[:-1]]
    assert all(document["object"] == "chat.completion.chunk" for document in documents)
    assert (
        "".join(document["choices"][0]["delta"].get("content", "") for document in documents)
        == "Hello from the fixture"
    )
    assert await coordinator.active_run_id(TARGET.target_id) is None


class FixtureAgentAdapter:
    @property
    def profile(self) -> AgentRuntimeProfile:
        return PROFILE

    async def run(self, command: StartRunCommand) -> AsyncGenerator[AgentAdapterEvent, None]:
        assert command.model == TARGET.target_id
        assert command.messages[-1].content == "Say hello"
        yield AgentAdapterTextDelta(delta="Hello")
        yield AgentAdapterTextDelta(delta=" from the fixture")
        yield AgentAdapterCompleted(
            usage=TokenUsage(input_tokens=2, output_tokens=4),
        )


class FailingAgentAdapter(FixtureAgentAdapter):
    async def run(self, command: StartRunCommand) -> AsyncGenerator[AgentAdapterEvent, None]:
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
    return AgentHostService(
        TARGET,
        runtime or FixtureAgentAdapter(),
        AgentRunCoordinator((TARGET,)),
    )


def test_chat_completions_openapi_describes_the_official_sdk_request_body() -> None:
    app = create_app(cast(GatewaySessionCoordinator, object()), agent_host=_agent_host())

    assert app.title == "Mabrid"
    operation = app.openapi()["paths"]["/v1/chat/completions"]["post"]
    host_operation = app.openapi()["paths"]["/api/v1/host/sessions/{session_id}/runs"]["post"]
    assert "text/event-stream" in host_operation["responses"]["200"]["content"]
    assert "application/json" in host_operation["responses"]["409"]["content"]
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


async def test_official_openai_client_receives_incremental_chat_chunks() -> None:
    async with _openai_client(_agent_host()) as client:
        stream = await client.chat.completions.create(
            model="caller-model",
            messages=[{"role": "user", "content": "Say hello"}],
            stream=True,
            stream_options={"include_usage": True},
        )
        chunks = [chunk async for chunk in stream]

    assert [chunk.object for chunk in chunks] == ["chat.completion.chunk"] * 5
    assert len({chunk.id for chunk in chunks}) == 1
    assert len({chunk.created for chunk in chunks}) == 1
    assert all(chunk.model == TARGET.target_id for chunk in chunks)
    assert chunks[0].choices[0].delta.role == "assistant"
    assert [chunk.choices[0].delta.content for chunk in chunks[1:3]] == [
        "Hello",
        " from the fixture",
    ]
    assert chunks[3].choices[0].finish_reason == "stop"
    assert chunks[4].choices == []
    assert chunks[4].usage is not None
    assert chunks[4].usage.total_tokens == 6


async def test_raw_stream_ends_with_done_without_optional_usage() -> None:
    app = create_app(cast(GatewaySessionCoordinator, object()), agent_host=_agent_host())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "caller-model",
                "messages": [{"role": "user", "content": "Say hello"}],
                "stream": True,
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    lines = [line for line in response.text.splitlines() if line.startswith("data: ")]
    assert len(lines) == 5
    assert lines[-1] == "data: [DONE]"
    assert all('"usage"' not in line for line in lines[:-1])


async def test_stream_reports_provider_failure_without_successful_finish() -> None:
    async with _openai_client(_agent_host(FailingAgentAdapter())) as client:
        stream = await client.chat.completions.create(
            model="caller-model",
            messages=[{"role": "user", "content": "Say hello"}],
            stream=True,
        )
        with pytest.raises(Exception, match="Provider unavailable for fixture-target"):
            _ = [chunk async for chunk in stream]


async def test_failed_sse_does_not_emit_success_or_done() -> None:
    agent_host = _agent_host(FailingAgentAdapter())
    app = create_app(cast(GatewaySessionCoordinator, object()), agent_host=agent_host)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "fixture-target",
                "messages": [{"role": "user", "content": "Say hello"}],
                "stream": True,
            },
        )

    lines = [line for line in response.text.splitlines() if line.startswith("data: ")]
    assert response.status_code == 200
    assert len(lines) == 2
    assert json.loads(lines[0][6:])["choices"][0]["delta"]["role"] == "assistant"
    assert json.loads(lines[1][6:])["error"]["message"] == (
        "Provider unavailable for fixture-target"
    )
    assert await agent_host.coordinator.active_run_id(TARGET.target_id) is None


async def test_closing_http_chunk_generator_closes_runtime_stream() -> None:
    class ClosableAdapter(FixtureAgentAdapter):
        closed = False

        async def run(self, command: StartRunCommand) -> AsyncGenerator[AgentAdapterEvent, None]:
            try:
                yield AgentAdapterTextDelta(delta="partial")
                yield AgentAdapterCompleted()
            finally:
                self.closed = True

    adapter = ClosableAdapter()
    agent_host = _agent_host(adapter)
    command = StartRunCommand(
        model="caller-model",
        messages=(AgentMessage(role="user", content="Say hello"),),
    )
    chunks = _stream_chat_completion(
        HostEventStream(agent_host), command, model=TARGET.target_id, include_usage=False
    )
    assert '"role":"assistant"' in await anext(chunks)
    assert '"content":"partial"' in await anext(chunks)

    await chunks.aclose()

    assert adapter.closed is True
    assert await agent_host.coordinator.active_run_id(TARGET.target_id) is None


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
