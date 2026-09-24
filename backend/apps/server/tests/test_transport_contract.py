from __future__ import annotations

from functools import partial
import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from mabrid.application.agent_host import AgentMessage, StartRunCommand
from mabrid.application.agent_host.integrations.hermes import HermesChatCompletionsAdapter
from mabrid.application.host import HostAgentEvent, HostWidgetEvent
from mabrid.application.mcp_apps import WidgetCreated, WidgetFailed
from mabrid.bridge import (
    ReadResourceResult,
    ResourceContent,
    ResourceDescriptor,
    ToolCallResult,
    ToolDescriptor,
    UpstreamConfig,
    UpstreamIdentity,
)
from openai import AsyncOpenAI
from pydantic import SecretStr
from mabrid.application.gateway.inspection import BridgeSessionStore, BridgeSessionStoreFactory
from mabrid.application.gateway.sessions import (
    BridgeSessionRecord,
    BridgeSessionStatus,
    GatewaySessionCoordinator,
)
from mabrid.application.gateway.topology import (
    EndpointBindingRevision,
    EndpointTopologyRevision,
    StdioConnection,
    UpstreamRevision,
)

from mabrid.server.api import create_app
from mabrid.server.composition import bootstrap_server
from mabrid.server.config import (
    BridgeRuntimeConfig,
    EndpointBindingFileConfig,
    EndpointFileConfig,
    RuntimeAgentHostConfig,
    RuntimeConfiguration,
    RuntimeHermesAgentConfig,
    RuntimeUpstreamConfig,
    StorageConfig,
)
import mabrid.server.composition.agent_host as agent_host_composition
import mabrid.server.composition.gateway as gateway_composition


class FixtureClient:
    async def connect(self, config: UpstreamConfig) -> UpstreamIdentity:
        return UpstreamIdentity(
            server_name="Fixture MCP",
            server_version="1.0.0",
            protocol_version="2025-11-25",
            supports_tools=True,
            supports_resources=True,
        )

    async def list_tools(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                name="echo",
                description="Echo text",
                input_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                },
            )
        ]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        return ToolCallResult(content=({"type": "text", "text": str(arguments.get("text", ""))},))

    async def list_resources(self) -> list[ResourceDescriptor]:
        return [ResourceDescriptor(name="status", uri="data://status", mime_type="text/plain")]

    async def read_resource(self, uri: str) -> ReadResourceResult:
        return ReadResourceResult(
            contents=(ResourceContent(uri=uri, mime_type="text/plain", text="ready"),)
        )

    async def close(self) -> None:
        return None


class FixtureClientFactory:
    def create(self, config: UpstreamConfig) -> FixtureClient:
        return FixtureClient()


class SingleTopologyReader:
    def __init__(self, revision: EndpointTopologyRevision) -> None:
        self.revision = revision

    async def list_current_revisions(self) -> list[EndpointTopologyRevision]:
        return [self.revision]

    async def resolve_current_revision(self, endpoint_slug: str) -> EndpointTopologyRevision | None:
        return self.revision if endpoint_slug == self.revision.slug else None

    async def get_revision(self, revision_id: UUID) -> EndpointTopologyRevision | None:
        return self.revision if revision_id == self.revision.revision_id else None


class MemorySessionRepository:
    def __init__(self) -> None:
        self.records: dict[UUID, BridgeSessionRecord] = {}

    async def add(self, session: BridgeSessionRecord) -> None:
        self.records[session.session_id] = session.model_copy(deep=True)

    async def update(self, session: BridgeSessionRecord) -> None:
        self.records[session.session_id] = session.model_copy(deep=True)

    async def get(self, session_id: UUID) -> BridgeSessionRecord | None:
        return self.records.get(session_id)

    async def list(self, endpoint_id: UUID | None = None) -> list[BridgeSessionRecord]:
        return [
            record
            for record in self.records.values()
            if endpoint_id is None or record.endpoint_id == endpoint_id
        ]


class MemoryStoreFactory:
    def __init__(self) -> None:
        self.stores: dict[UUID, BridgeSessionStore] = {}

    async def create(self, session_id: UUID) -> BridgeSessionStore:
        store = cast(BridgeSessionStore, AsyncMock(spec=BridgeSessionStore))
        self.stores[session_id] = store
        return store

    async def get(self, session_id: UUID) -> BridgeSessionStore | None:
        return self.stores.get(session_id)

    async def remove(self, session_id: UUID) -> None:
        self.stores.pop(session_id, None)


def rpc_request(
    method: str, *, request_id: int | None = None, params: object = None
) -> dict[str, Any]:
    request: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        request["id"] = request_id
    if params is not None:
        request["params"] = params
    return request


def response_payload(response: httpx.Response) -> dict[str, Any]:
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        data = next(
            line.removeprefix("data: ")
            for line in response.text.splitlines()
            if line.startswith("data: ")
        )
        return cast(dict[str, Any], json.loads(data))
    return cast(dict[str, Any], response.json())


async def test_composed_server_supports_mcp_2025_streamable_http_contract() -> None:
    upstream = UpstreamRevision(
        server_id=uuid4(),
        slug="fixture",
        display_name="Fixture MCP",
        connection=StdioConnection(command="fixture-server"),
    )
    revision = EndpointTopologyRevision(
        endpoint_id=uuid4(),
        slug="fixture",
        display_name="Fixture MCP",
        bindings=(EndpointBindingRevision(upstream=upstream),),
    )
    sessions = MemorySessionRepository()
    coordinator = GatewaySessionCoordinator(
        SingleTopologyReader(revision),
        sessions,
        cast(BridgeSessionStoreFactory, MemoryStoreFactory()),
        upstream_client_factory=FixtureClientFactory(),
    )
    await coordinator.load_published_endpoints()
    app = create_app(coordinator)
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
    }

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            initialized = await client.post(
                "/mcp/fixture",
                headers=headers,
                json=rpc_request(
                    "initialize",
                    request_id=1,
                    params={
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "contract-test", "version": "1.0.0"},
                    },
                ),
            )
            assert initialized.status_code == 200
            session_id = initialized.headers["mcp-session-id"]
            assert response_payload(initialized)["result"]["protocolVersion"] == "2025-11-25"

            session_headers = {**headers, "mcp-session-id": session_id}
            notification = await client.post(
                "/mcp/fixture",
                headers=session_headers,
                json=rpc_request("notifications/initialized"),
            )
            assert notification.status_code == 202

            tools = await client.post(
                "/mcp/fixture",
                headers=session_headers,
                json=rpc_request("tools/list", request_id=2, params={}),
            )
            assert response_payload(tools)["result"]["tools"][0]["name"] == "echo"

            called = await client.post(
                "/mcp/fixture",
                headers=session_headers,
                json=rpc_request(
                    "tools/call",
                    request_id=3,
                    params={"name": "echo", "arguments": {"text": "hello"}},
                ),
            )
            assert response_payload(called)["result"]["content"][0]["text"] == "hello"

            resources = await client.post(
                "/mcp/fixture",
                headers=session_headers,
                json=rpc_request("resources/list", request_id=4, params={}),
            )
            assert response_payload(resources)["result"]["resources"][0]["uri"] == "data://status"

            resource = await client.post(
                "/mcp/fixture",
                headers=session_headers,
                json=rpc_request(
                    "resources/read",
                    request_id=5,
                    params={"uri": "data://status"},
                ),
            )
            assert response_payload(resource)["result"]["contents"][0]["text"] == "ready"

            closed = await client.delete("/mcp/fixture", headers=session_headers)
            assert closed.status_code == 200

    [record] = await sessions.list()
    assert record.status is BridgeSessionStatus.CLOSED


async def test_streamed_agent_run_projects_real_mcp_tool_into_host_widget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class UiFixtureClient(FixtureClient):
        def __init__(self) -> None:
            self.resource_reads = 0
            self.fail_resource_read = False

        async def list_tools(self) -> list[ToolDescriptor]:
            return [
                ToolDescriptor(
                    name="inspect",
                    ui_resource_uri="ui://fixture/inspect",
                    input_schema={"type": "object"},
                )
            ]

        async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
            assert tool_name == "inspect"
            return ToolCallResult(content=({"type": "text", "text": "inspected"},))

        async def read_resource(self, uri: str) -> ReadResourceResult:
            assert uri == "ui://fixture/inspect"
            self.resource_reads += 1
            if self.fail_resource_read:
                raise RuntimeError("UI resource unavailable")
            return ReadResourceResult(
                contents=(
                    ResourceContent(uri=uri, text=f"<p>inspection {self.resource_reads}</p>"),
                )
            )

    class UiFixtureFactory:
        def __init__(self) -> None:
            self.client = UiFixtureClient()

        def create(self, config: UpstreamConfig) -> UiFixtureClient:
            return self.client

    upstream_factory = UiFixtureFactory()
    monkeypatch.setattr(
        gateway_composition,
        "GatewaySessionCoordinator",
        partial(GatewaySessionCoordinator, upstream_client_factory=upstream_factory),
    )
    handler_errors: list[Exception] = []
    app = None

    async def hermes_response(request: httpx.Request) -> httpx.Response:
        try:
            return await respond_to_hermes(request)
        except Exception as exc:
            handler_errors.append(exc)
            raise

    async def respond_to_hermes(request: httpx.Request) -> httpx.Response:
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
        assert request.url.path == "/v1/chat/completions"
        assert json.loads(request.content)["stream"] is True
        assert app is not None
        headers = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            initialized = await client.post(
                "/mcp/fixture",
                headers=headers,
                json=rpc_request(
                    "initialize",
                    request_id=1,
                    params={
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "hermes-fixture", "version": "1.0.0"},
                    },
                ),
            )
            assert initialized.status_code == 200
            session_headers = {**headers, "mcp-session-id": initialized.headers["mcp-session-id"]}
            notification = await client.post(
                "/mcp/fixture",
                headers=session_headers,
                json=rpc_request("notifications/initialized"),
            )
            assert notification.status_code == 202
            tools = await client.post(
                "/mcp/fixture",
                headers=session_headers,
                json=rpc_request("tools/list", request_id=2, params={}),
            )
            [tool] = response_payload(tools)["result"]["tools"]
            assert tool["name"] == "inspect"
            assert tool["_meta"]["ui"]["resourceUri"] == "ui://fixture/inspect"
            called = await client.post(
                "/mcp/fixture",
                headers=session_headers,
                json=rpc_request(
                    "tools/call",
                    request_id=3,
                    params={"name": "inspect", "arguments": {}},
                ),
            )
            assert response_payload(called)["result"]["content"][0]["text"] == "inspected"

        def chunk(choices: list[dict[str, object]], usage: dict[str, int] | None = None) -> str:
            return (
                "data: "
                + json.dumps(
                    {
                        "id": "chatcmpl-fixture",
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
                chunk([{"index": 0, "delta": {"content": "Inspected"}, "finish_reason": None}])
                + chunk([{"index": 0, "delta": {}, "finish_reason": "stop"}])
                + chunk([], {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3})
                + "data: [DONE]\n\n"
            ),
        )

    runtime_client = AsyncOpenAI(
        base_url="http://hermes.test/v1",
        api_key="fixture-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(hermes_response)),
    )
    runtime = HermesChatCompletionsAdapter(
        base_url="http://unused.test/v1", api_key="unused", client=runtime_client
    )
    monkeypatch.setattr(agent_host_composition, "_build_agent_runtime", lambda _config: runtime)
    configuration = RuntimeConfiguration(
        config_path=tmp_path / "fixture.yaml",
        bridge=BridgeRuntimeConfig(advertised_base_url="http://mabrid.test:8765"),
        storage=StorageConfig(sqlite_path=tmp_path / "gateway.db", auto_migrate=True),
        upstreams={"fixture": RuntimeUpstreamConfig(transport="stdio", command="fixture-server")},
        endpoints={
            "fixture": EndpointFileConfig(bindings=[EndpointBindingFileConfig(upstream="fixture")])
        },
        diagnostic_upstream=None,
        agent_host=RuntimeAgentHostConfig(
            enabled=True,
            mcp_apps_enabled=True,
            target_id="fixture-target",
            endpoint_slug="fixture",
            runtime=RuntimeHermesAgentConfig(
                base_url="http://hermes.test/v1", api_key=SecretStr("fixture-key")
            ),
        ),
    )
    result = await bootstrap_server(configuration)
    try:
        assert result.agent_host is not None
        assert result.mcp_apps is not None
        assert result.host_events is not None
        service = result.agent_host.service
        host = result.host_events
        widget_events = result.mcp_apps.events
        attributions = result.agent_host.operation_attributions
        runs = service.coordinator
        target = service.target
        app = create_app(result.gateway, agent_host=service, host_events=host)
        command = StartRunCommand(
            model=target.target_id,
            messages=(AgentMessage(role="user", content="Inspect the fixture"),),
        )
        async with app.router.lifespan_context(app):
            events = [event async for event in host.run_events(command)]
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as inbound:
                streamed = await inbound.post(
                    "/v1/chat/completions",
                    json={
                        "model": target.target_id,
                        "messages": [{"role": "user", "content": "Inspect again"}],
                        "stream": True,
                        "stream_options": {"include_usage": True},
                    },
                )
                upstream_factory.client.fail_resource_read = True
                failed_resource = await inbound.post(
                    "/v1/chat/completions",
                    json={
                        "model": target.target_id,
                        "messages": [{"role": "user", "content": "Inspect without a widget"}],
                        "stream": True,
                    },
                )
    finally:
        await runtime.close()
        await result.database.close()

    widgets = [event for event in events if isinstance(event, HostWidgetEvent)]
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert events[-1].event.kind == "run.completed", (events[-1].event, handler_errors)
    assert len(widgets) == 1
    assert isinstance(widgets[0].event, WidgetCreated)
    widget = widgets[0].event.widget
    assert widget.run_id == command.run_id
    assert widget.target_id == target.target_id
    assert widget.tool_name == "inspect"
    assert widget.tool_result.content[0]["text"] == "inspected"
    assert widget.resource_contents[0].text == "<p>inspection 1</p>"
    assert upstream_factory.client.resource_reads == 3
    assert widgets[0].sequence < events[-1].sequence
    assert isinstance(events[-1], HostAgentEvent)
    assert events[-1].event.kind == "run.completed"
    assert events[-1].event.result.output_text == "Inspected"
    assert events[-1].event.result.usage.total_tokens == 3
    first_attribution = await attributions.get(widget.session_key, widget.operation_key)
    assert first_attribution is not None
    assert first_attribution.run_id == command.run_id
    assert await runs.active_run_id(target.target_id) is None
    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")
    chunks = [
        json.loads(line.removeprefix("data: "))
        for line in streamed.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    assert streamed.text.rstrip().endswith("data: [DONE]")
    assert [choice["delta"] for chunk in chunks for choice in chunk["choices"]][1] == {
        "content": "Inspected"
    }
    assert chunks[-1]["usage"]["total_tokens"] == 3
    second_run_id = UUID(chunks[0]["id"].removeprefix("chatcmpl-"))
    assert second_run_id != command.run_id
    [second_widget] = await widget_events.list_for_run(second_run_id)
    assert isinstance(second_widget, WidgetCreated)
    assert second_widget.widget.resource_contents[0].text == "<p>inspection 2</p>"
    assert second_widget.widget.operation_key != widget.operation_key
    second_attribution = await attributions.get(
        second_widget.widget.session_key, second_widget.widget.operation_key
    )
    assert second_attribution is not None
    assert second_attribution.run_id == second_run_id
    assert failed_resource.status_code == 200
    assert failed_resource.text.rstrip().endswith("data: [DONE]")
    failed_chunks = [
        json.loads(line.removeprefix("data: "))
        for line in failed_resource.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    assert failed_chunks[-1]["choices"][0]["finish_reason"] == "stop"
    failed_run_id = UUID(failed_chunks[0]["id"].removeprefix("chatcmpl-"))
    [failed_widget] = await widget_events.list_for_run(failed_run_id)
    assert isinstance(failed_widget, WidgetFailed)
    assert failed_widget.tool_result.content[0]["text"] == "inspected"
    assert failed_widget.application_resource_uri == "ui://fixture/inspect"
    failed_attribution = await attributions.get(
        failed_widget.session_key, failed_widget.operation_key
    )
    assert failed_attribution is not None
    assert failed_attribution.run_id == failed_run_id
    assert await runs.active_run_id(target.target_id) is None
