from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import json

import httpx
import pytest
from unittest.mock import Mock
from unittest.mock import AsyncMock
from mabrid.server.api import create_app
from mabrid.application.gateway.sessions import GatewaySessionCoordinator
from mabrid.application.host import HostSessionEventStream
from mabrid.server.api.host_contracts import HostStreamEvent
from httpx_sse import aconnect_sse
from httpx_sse import EventSource
from starlette.types import Message
from fastapi import FastAPI
import anyio
from mabrid.application.agent_host import AgentRunSettlement
from mabrid.application.host import (
    HostRunSettlement,
    compose_host_capabilities,
    NativeSessionPorts,
    HostAgentEvent,
    HostToolEvent,
    HostWidgetEvent,
)
from mabrid.application.agent_host import (
    AgentAdapterCompleted,
    AgentAdapterEvent,
    StartRunCommand,
    ToolInvocationStarted,
    ToolInvocationCompleted,
)
from collections.abc import AsyncGenerator, AsyncIterator
from mabrid.bridge import (
    ToolsPublished,
    ToolDescriptor,
    ToolCallStarted,
    ToolCallCompleted,
    ToolCallResult,
    BridgeErrorRaised,
    BridgeFailure,
    BridgeFailureCode,
)

from mabrid.application.agent_host import (
    AgentSessionRecord,
    RuntimeRunHandle,
    RuntimeSessionReference,
)
from mabrid.server.persistence import SqliteDatabase
from mabrid.server.persistence.agent_host import SqliteAgentSessionRepository
from mabrid.application.agent_host import (
    AgentSessionService,
    AgentSessionError,
    AgentRunCoordinator,
    AgentTarget,
    AgentRuntimeProfile,
    AgentRuntimeInterface,
    AgentEndpointAssignment,
    CreateAgentSessionCommand,
    StartSessionRunCommand,
    HistoryPageQuery,
)
from mabrid.application.agent_host.integrations.hermes import HermesSessionAdapter


TARGET = AgentTarget(
    target_id="fixture-target",
    runtime_profile=AgentRuntimeProfile(
        integration_kind="fixture",
        interface=AgentRuntimeInterface.OPENAI_CHAT_COMPLETIONS,
        capabilities=frozenset(),
    ),
    endpoint_assignment=AgentEndpointAssignment(endpoint_slug="fixture"),
)


async def test_first_party_session_http_keeps_history_remote_and_errors_safe(
    tmp_path: Path,
) -> None:
    fixture = NativeHermesFixture()
    adapter = HermesSessionAdapter(
        api_root="http://hermes.test/",
        api_key="fixture",
        runtime_binding_id="fixture-deployment",
        client=httpx.AsyncClient(transport=httpx.MockTransport(fixture.handle)),
    )
    database = SqliteDatabase(tmp_path / "http.db")
    await database.migrate()
    service = session_service(database, adapter)
    app = create_app(Mock(spec=GatewaySessionCoordinator), agent_sessions=service)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://mabrid.test"
        ) as client:
            first = await client.post("/api/v1/host/sessions", json={"title": "First"})
            second = await client.post("/api/v1/host/sessions", json={"title": "Second"})
            assert first.status_code == second.status_code == 201
            session_id = first.json()["session_id"]
            assert "remote_session_id" not in first.text and "fixture-deployment" not in first.text
            listing = await client.get("/api/v1/host/sessions", params={"limit": 1})
            assert listing.status_code == 200 and listing.json()["has_more"] is True
            assert listing.json()["sessions"][0]["binding_state"] == "unknown"
            reopened = await client.get(f"/api/v1/host/sessions/{session_id}")
            assert reopened.status_code == 200 and reopened.json()["binding_state"] == "available"
            history = await client.get(f"/api/v1/host/sessions/{session_id}/history")
            assert history.status_code == 200 and history.json()["messages"] == []
            invalid = await client.post("/api/v1/host/sessions", json={"private": "input-marker"})
            assert invalid.status_code == 422 and invalid.json()["code"] == "invalid_request"
            assert "input-marker" not in invalid.text
            fixture.messages.clear()
            missing = await client.get(f"/api/v1/host/sessions/{session_id}/history")
            assert (
                missing.status_code == 404 and missing.json()["code"] == "remote_session_not_found"
            )
            assert "api_1" not in missing.text
    finally:
        await adapter.close()
        await database.close()


@pytest.mark.parametrize("cancel_first", [True, False])
async def test_native_cancel_acknowledgement_order_and_session_control_binding(
    tmp_path: Path, cancel_first: bool
) -> None:
    fixture = NativeHermesFixture()
    requests: list[str] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return await fixture.handle(request)

    adapter = HermesSessionAdapter(
        api_root="http://hermes.test/",
        api_key="fixture",
        runtime_binding_id="fixture-deployment",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    database = SqliteDatabase(tmp_path / "cancel.db")
    await database.migrate()
    service = session_service(database, adapter)
    try:
        session = await service.create_session(CreateAgentSessionCommand())
        other = await service.create_session(CreateAgentSessionCommand())
        command = StartSessionRunCommand(session_id=session.session_id, input_text="Fixture")
        stream = service.run_session(command)
        await anext(stream)
        with pytest.raises(AgentSessionError) as wrong_session:
            await service.request_stop(command.run_id, session_id=other.session_id)
        assert wrong_session.value.code == "run_not_found"
        assert not any(path.endswith("/stop") for path in requests)
        with pytest.raises(AgentSessionError) as busy:
            await anext(
                service.run_session(
                    StartSessionRunCommand(session_id=other.session_id, input_text="Overlap")
                )
            )
        assert busy.value.code == "target_busy"
        if cancel_first:
            assert (
                await service.request_stop(command.run_id, session_id=session.session_id)
            ).accepted
            events = [event async for event in stream]
            assert events[-1].kind == "session_adapter.cancelled"
        else:
            await anext(stream)
            completed = await anext(stream)
            assert completed.kind == "session_adapter.completed"
            assert not (
                await service.request_stop(command.run_id, session_id=session.session_id)
            ).accepted
            assert not any(path.endswith("/stop") for path in requests)
            await stream.aclose()
        assert await service.coordinator.active_run_id(TARGET.target_id) is None
    finally:
        await adapter.close()
        await database.close()


async def test_first_party_http_stream_admits_before_headers_and_continues_selected_history(
    tmp_path: Path,
) -> None:
    fixture = NativeHermesFixture()
    adapter = HermesSessionAdapter(
        api_root="http://hermes.test/",
        api_key="fixture",
        runtime_binding_id="fixture-deployment",
        client=httpx.AsyncClient(transport=httpx.MockTransport(fixture.handle)),
    )
    database = SqliteDatabase(tmp_path / "runs-http.db")
    await database.migrate()
    service = session_service(database, adapter)
    app = create_app(
        Mock(spec=GatewaySessionCoordinator),
        agent_sessions=service,
        host_session_events=HostSessionEventStream(service),
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://mabrid.test"
        ) as client:
            first = (await client.post("/api/v1/host/sessions", json={})).json()["session_id"]
            second = (await client.post("/api/v1/host/sessions", json={})).json()["session_id"]
            for session_id, text in ((first, "First"), (second, "Second"), (first, "Continue")):
                async with aconnect_sse(
                    client,
                    "POST",
                    f"/api/v1/host/sessions/{session_id}/runs",
                    json={"input_text": text},
                ) as stream:
                    assert stream.response.status_code == 200
                    assert stream.response.headers["cache-control"] == "no-store"
                    frames = [frame async for frame in stream.aiter_sse()]
                events = [HostStreamEvent.model_validate_json(frame.data) for frame in frames]
                assert [frame.event for frame in frames] == [
                    "run.started",
                    "assistant.text.delta",
                    "assistant.text.completed",
                    "run.completed",
                ]
                assert [event.sequence for event in events] == [1, 2, 3, 4]
                assert all(
                    str(event.session_id) == session_id and event.run_id == events[0].run_id
                    for event in events
                )
                assert all(
                    frame.id == str(event.event_id)
                    for frame, event in zip(frames, events, strict=True)
                )
                wire = "".join(frame.data for frame in frames)
                for private_field in (
                    "remote_session_id",
                    "remote_run_id",
                    "runtime_binding_id",
                    "session_key",
                    "operation_key",
                ):
                    assert private_field not in wire
            assert fixture.inputs == [
                {"message": "First"},
                {"message": "Second"},
                {"message": "Continue"},
            ]
            first_history = await client.get(f"/api/v1/host/sessions/{first}/history")
            second_history = await client.get(f"/api/v1/host/sessions/{second}/history")
            assert (
                len(first_history.json()["messages"]) == 2
                and len(second_history.json()["messages"]) == 1
            )
            missing = await client.post(
                f"/api/v1/host/sessions/{uuid4()}/runs", json={"input_text": "Missing"}
            )
            assert missing.status_code == 404 and missing.headers["content-type"].startswith(
                "application/json"
            )
            assert missing.json()["code"] == "session_not_found"
            invalid = await client.post(
                f"/api/v1/host/sessions/{first}/runs", json={"input_text": "", "messages": []}
            )
            assert invalid.status_code == 422 and invalid.json()["code"] == "invalid_request"
            assert await service.coordinator.active_run_id(TARGET.target_id) is None
    finally:
        await adapter.close()
        await database.close()


@pytest.mark.parametrize(
    "failure_mode",
    ["before", "after", "unknown", "binding", "missing_remote", "storage", "disabled", "replay"],
)
async def test_first_party_host_maps_safe_http_and_stream_failures(
    tmp_path: Path, failure_mode: str
) -> None:
    fixture = NativeHermesFixture()

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/stream") and failure_mode == "before":
            return httpx.Response(503, text="private-runtime-url-and-secret")
        if request.url.path.endswith("/chat/stream") and failure_mode in {"after", "unknown"}:
            fixture.terminal = failure_mode != "unknown"
            remote_id = request.url.path.split("/")[3]
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=f"event: run.started\ndata: {json.dumps({'run_id': 'private-remote-run', 'session_id': remote_id, 'seq': 1})}\n\nevent: error\ndata: {json.dumps({'run_id': 'private-remote-run', 'session_id': remote_id, 'seq': 2, 'message': 'private-runtime-url-and-secret'})}\n\n",
            )
        if request.url.path.startswith("/v1/runs/"):
            return httpx.Response(
                200,
                json={
                    "run_id": "private-remote-run",
                    "status": "completed" if fixture.terminal else "stopping",
                },
            )
        return await fixture.handle(request)

    adapter = HermesSessionAdapter(
        api_root="http://hermes.test/",
        api_key="fixture",
        runtime_binding_id="fixture-deployment",
        settlement_timeout_seconds=0.02,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    database = SqliteDatabase(tmp_path / "failures-http.db")
    await database.migrate()
    service = session_service(database, adapter)
    session = await service.create_session(CreateAgentSessionCommand())
    if failure_mode == "binding":
        service = session_service(database, adapter, binding_id="other-runtime")
    elif failure_mode == "missing_remote":
        fixture.messages.clear()
    elif failure_mode == "storage":
        repository = AsyncMock()
        repository.list_sessions.side_effect = RuntimeError("private-runtime-url-and-secret")
        service = AgentSessionService(
            target_id=TARGET.target_id,
            runtime_binding_id="fixture-deployment",
            repository=repository,
            catalog=adapter,
            history=adapter,
            execution=adapter,
            control=adapter,
            coordinator=AgentRunCoordinator((TARGET,)),
        )
    app = create_app(
        Mock(spec=GatewaySessionCoordinator),
        agent_sessions=None if failure_mode == "disabled" else service,
        host_session_events=None if failure_mode == "disabled" else HostSessionEventStream(service),
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://mabrid.test"
        ) as client:
            if failure_mode == "storage":
                response = await client.get("/api/v1/host/sessions")
            else:
                response = await client.post(
                    f"/api/v1/host/sessions/{session.session_id}/runs",
                    json={"input_text": "Fixture"},
                    headers={"Last-Event-ID": "private-replay-cursor"}
                    if failure_mode == "replay"
                    else {},
                )
            for private in (
                "private-runtime-url-and-secret",
                "private-remote-run",
                "private-replay-cursor",
                "remote_session_id",
                "remote_run_id",
                "session_key",
                "operation_key",
            ):
                assert private not in response.text
            if failure_mode in {"after", "unknown"}:
                assert response.status_code == 200
                frames = list(EventSource(response).iter_sse())
                events = [HostStreamEvent.model_validate_json(frame.data) for frame in frames]
                assert [frame.event for frame in frames] == ["run.started", "run.failed"]
                assert [event.sequence for event in events] == [1, 2]
                failed = events[-1].event
                assert failed.kind == "run.failed"
                assert failed.error.code == (
                    "run_state_unknown" if failure_mode == "unknown" else "runtime_unavailable"
                )
                pending = await SqliteAgentSessionRepository(
                    database.session_factory
                ).get_unsettled_run(TARGET.target_id)
                assert (pending is not None) == (failure_mode == "unknown")
            else:
                status, code = {
                    "before": (503, "runtime_unavailable"),
                    "binding": (409, "runtime_binding_changed"),
                    "missing_remote": (404, "remote_session_not_found"),
                    "storage": (500, "internal_error"),
                    "disabled": (503, "unsupported_operation"),
                    "replay": (503, "unsupported_operation"),
                }[failure_mode]
                assert response.status_code == status and response.json()["code"] == code
                assert response.headers["content-type"].startswith("application/json")
    finally:
        await adapter.close()
        await database.close()


class NativeHermesFixture:
    def __init__(self) -> None:
        self.messages: dict[str, list[dict[str, object]]] = {}
        self.inputs: list[dict[str, object]] = []
        self.terminal = True
        self.resumed = False

    async def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/sessions" and request.method == "POST":
            remote_id = f"api_{len(self.messages) + 1}"
            self.messages[remote_id] = []
            return httpx.Response(
                201, json={"object": "hermes.session", "session": {"id": remote_id}}
            )
        if path.startswith("/v1/runs/"):
            return httpx.Response(
                200,
                json={
                    "run_id": "run_fixture",
                    "status": "stopping"
                    if path.endswith("/stop") or not self.terminal
                    else "completed",
                },
            )
        remote_id = path.split("/")[3]
        if remote_id not in self.messages:
            return httpx.Response(404, json={"error": {"code": "session_not_found"}})
        if path.endswith("/messages"):
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "session_id": remote_id,
                    "data": self.messages[remote_id],
                    "pagination": {
                        "limit": int(request.url.params["limit"]),
                        "offset": int(request.url.params["offset"]),
                        "order": request.url.params["order"],
                        "returned": len(self.messages[remote_id]),
                    },
                },
            )
        if path.endswith("/chat/stream"):
            payload = json.loads(request.content)
            self.inputs.append(payload)
            self.messages[remote_id].append(
                {
                    "id": len(self.messages[remote_id]) + 1,
                    "role": "user",
                    "content": payload["message"],
                }
            )
            effective = remote_id
            if self.resumed:
                effective = remote_id + "_resumed"
                self.messages[effective] = list(self.messages[remote_id])
            frames = [("run.started", {"session_id": remote_id})]
            if self.terminal:
                frames += [
                    ("assistant.delta", {"delta": "Reply"}),
                    ("assistant.completed", {"content": "Reply", "session_id": effective}),
                    (
                        "run.completed",
                        {"session_id": effective, "usage": {"input_tokens": 3, "output_tokens": 2}},
                    ),
                    ("done", {}),
                ]
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text="".join(
                    f"event: {name}\ndata: {json.dumps({'run_id': 'run_fixture', 'session_id': remote_id, 'seq': index, **data})}\n\n"
                    for index, (name, data) in enumerate(frames, 1)
                ),
            )
        return httpx.Response(200, json={"object": "hermes.session", "session": {"id": remote_id}})


class PausedNativeHermesFixture(NativeHermesFixture):
    def __init__(self) -> None:
        super().__init__()
        self.terminal = False
        self.paused = anyio.Event()
        self.resume = anyio.Event()
        self.stream_closed = anyio.Event()
        self.request_paths: list[str] = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.request_paths.append(request.url.path)
        response = await super().handle(request)
        if request.url.path.endswith("/chat/stream"):
            fixture = self
            remote_id = request.url.path.split("/")[3]
            initial = response.content

            class PausedSse(httpx.AsyncByteStream):
                async def __aiter__(self) -> AsyncIterator[bytes]:
                    yield initial
                    fixture.paused.set()
                    await fixture.resume.wait()
                    for index, (name, data) in enumerate(
                        (
                            ("assistant.delta", {"delta": "Reply"}),
                            ("assistant.completed", {"content": "Reply"}),
                            ("run.completed", {"usage": {"input_tokens": 3, "output_tokens": 2}}),
                            ("done", {}),
                        ),
                        2,
                    ):
                        yield f"event: {name}\ndata: {json.dumps({'run_id': 'run_fixture', 'session_id': remote_id, 'seq': index, **data})}\n\n".encode()

                async def aclose(self) -> None:
                    fixture.stream_closed.set()

            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=PausedSse()
            )
        return response


class HostAsgiProbe:
    def __init__(self, app: FastAPI, *, fail_send: bool = False) -> None:
        self.app = app
        self.fail_send = fail_send
        self.disconnect = anyio.Event()
        self.first_frame = anyio.Event()
        self.finished = anyio.Event()
        self.messages: list[Message] = []
        self.error: Exception | None = None
        self.event_arrived = anyio.Condition()

    async def wait_events(self, count: int) -> list[HostStreamEvent]:
        async with self.event_arrived:
            while len(self.events()) < count:
                await self.event_arrived.wait()
            return self.events()

    def events(self) -> list[HostStreamEvent]:
        wire = b"".join(
            message.get("body", b"")
            for message in self.messages
            if message["type"] == "http.response.body"
        )
        response = httpx.Response(200, headers={"content-type": "text/event-stream"}, content=wire)
        return [
            HostStreamEvent.model_validate_json(event.data)
            for event in EventSource(response).iter_sse()
            if event.data
        ]

    async def run(self, path: str) -> None:
        requested = False

        async def receive() -> Message:
            nonlocal requested
            if not requested:
                requested = True
                return {
                    "type": "http.request",
                    "body": json.dumps({"input_text": "Fixture"}).encode(),
                    "more_body": False,
                }
            await self.disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            self.messages.append(message)
            if self.fail_send and message["type"] == "http.response.start":
                raise OSError("fixture client send failed")
            if message["type"] == "http.response.body" and b"data:" in message.get("body", b""):
                self.first_frame.set()
                async with self.event_arrived:
                    self.event_arrived.notify_all()

        try:
            await self.app(
                {
                    "type": "http",
                    "asgi": {"version": "3.0", "spec_version": "2.4"},
                    "http_version": "1.1",
                    "method": "POST",
                    "scheme": "http",
                    "path": path,
                    "raw_path": path.encode(),
                    "root_path": "",
                    "query_string": b"",
                    "headers": [(b"content-type", b"application/json")],
                    "server": ("mabrid.test", 80),
                    "client": ("client", 1234),
                },
                receive,
                send,
            )
        except Exception as exc:
            self.error = exc
        finally:
            self.finished.set()


@pytest.mark.parametrize("exit_mode", ["cancel", "disconnect", "send_failure", "before_handle"])
async def test_first_party_http_lifecycle_keeps_unknown_ownership_and_confirms_only_user_cancel(
    tmp_path: Path, exit_mode: str
) -> None:
    fixture = PausedNativeHermesFixture()

    async def handle(request: httpx.Request) -> httpx.Response:
        response = await fixture.handle(request)
        if exit_mode == "before_handle" and request.url.path.endswith("/chat/stream"):

            class BeforeHandleSse(httpx.AsyncByteStream):
                async def __aiter__(self) -> AsyncIterator[bytes]:
                    fixture.paused.set()
                    await fixture.resume.wait()
                    yield b""

                async def aclose(self) -> None:
                    fixture.stream_closed.set()

            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=BeforeHandleSse()
            )
        return response

    adapter = HermesSessionAdapter(
        api_root="http://hermes.test/",
        api_key="fixture",
        runtime_binding_id="fixture-deployment",
        settlement_timeout_seconds=0.02,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    database = SqliteDatabase(tmp_path / "lifecycle-http.db")
    await database.migrate()
    repository = SqliteAgentSessionRepository(database.session_factory)
    service = session_service(database, adapter)
    app = create_app(
        Mock(spec=GatewaySessionCoordinator),
        agent_sessions=service,
        host_session_events=HostSessionEventStream(service),
    )
    first = await service.create_session(CreateAgentSessionCommand())
    second = await service.create_session(CreateAgentSessionCommand())
    probe = HostAsgiProbe(app, fail_send=exit_mode == "send_failure")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://mabrid.test"
        ) as client:
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(probe.run, f"/api/v1/host/sessions/{first.session_id}/runs")
                if exit_mode == "before_handle":
                    await fixture.paused.wait()
                    assert not probe.first_frame.is_set()
                    probe.disconnect.set()
                elif exit_mode == "send_failure":
                    pass
                else:
                    await probe.first_frame.wait()
                    await fixture.paused.wait()
                    run_id = probe.events()[0].run_id
                    metadata = await client.get(f"/api/v1/host/sessions/{second.session_id}")
                    assert metadata.json()["target_run"] == {
                        "session_id": str(first.session_id),
                        "run_id": str(run_id),
                        "state": "active",
                    }
                    busy = await client.post(
                        f"/api/v1/host/sessions/{second.session_id}/runs",
                        json={"input_text": "Overlap"},
                    )
                    assert busy.status_code == 409 and busy.headers["content-type"].startswith(
                        "application/json"
                    )
                    assert busy.json()["code"] == "target_busy"
                    assert fixture.inputs == [{"message": "Fixture"}]
                    assert (
                        await client.get(f"/api/v1/host/sessions/{second.session_id}/history")
                    ).status_code == 200
                    wrong_cancel = await client.post(
                        f"/api/v1/host/sessions/{second.session_id}/runs/{run_id}/cancel"
                    )
                    assert (
                        wrong_cancel.status_code == 404
                        and wrong_cancel.json()["code"] == "run_not_found"
                    )
                    assert not any(path.endswith("/stop") for path in fixture.request_paths)
                    if exit_mode == "cancel":
                        cancelled = await client.post(
                            f"/api/v1/host/sessions/{first.session_id}/runs/{run_id}/cancel"
                        )
                        assert cancelled.status_code == 202 and cancelled.json()["accepted"] is True
                        assert cancelled.json()["settlement"] == "unconfirmed"
                        assert not probe.finished.is_set()
                        assert await service.coordinator.active_run_id(TARGET.target_id) == run_id
                        fixture.terminal = True
                        fixture.resume.set()
                    else:
                        probe.disconnect.set()
                with anyio.fail_after(1):
                    await probe.finished.wait()
            assert fixture.stream_closed.is_set()
            if exit_mode == "cancel":
                events = probe.events()
                assert events[-1].event.kind == "run.cancelled"
                assert "run.completed" not in [event.event.kind for event in events]
                assert await repository.get_unsettled_run(TARGET.target_id) is None
                assert await service.coordinator.active_run_id(TARGET.target_id) is None
                assert probe.error is None
            else:
                pending = await repository.get_unsettled_run(TARGET.target_id)
                assert pending is not None
                assert await service.coordinator.active_run_id(TARGET.target_id) == pending.run_id
                assert not any(
                    event.event.kind in {"run.completed", "run.cancelled"}
                    for event in probe.events()
                )
                listing = await client.get("/api/v1/host/sessions")
                assert listing.json()["sessions"][0]["target_run"] == {
                    "session_id": str(first.session_id),
                    "run_id": str(pending.run_id),
                    "state": "unsettled",
                }
                blocked = await client.post(
                    f"/api/v1/host/sessions/{second.session_id}/runs",
                    json={"input_text": "Must not replay"},
                )
                assert blocked.status_code == 409 and blocked.json()["code"] == "run_state_unknown"
                assert fixture.inputs == [{"message": "Fixture"}]
                if exit_mode == "before_handle":
                    assert pending.remote_run_id is None
                    reconcile = await client.post(
                        f"/api/v1/host/sessions/{first.session_id}/runs/{pending.run_id}/reconcile"
                    )
                    assert reconcile.status_code == 200 and reconcile.json()["settled"] is False
                else:
                    assert pending.remote_run_id == "run_fixture"
                    fixture.terminal = True
                    reconcile = await client.post(
                        f"/api/v1/host/sessions/{first.session_id}/runs/{pending.run_id}/reconcile"
                    )
                    assert reconcile.status_code == 200 and reconcile.json()["settled"] is True
                    assert await service.coordinator.active_run_id(TARGET.target_id) is None
                if exit_mode == "send_failure":
                    assert probe.error is not None
    finally:
        await adapter.close()
        await database.close()


def session_service(
    database: SqliteDatabase,
    adapter: HermesSessionAdapter,
    coordinator: AgentRunCoordinator | None = None,
    *,
    binding_id: str = "fixture-deployment",
    settlement: AgentRunSettlement | None = None,
) -> AgentSessionService:
    return AgentSessionService(
        target_id=TARGET.target_id,
        runtime_binding_id=binding_id,
        repository=SqliteAgentSessionRepository(database.session_factory),
        catalog=adapter,
        history=adapter,
        execution=adapter,
        control=adapter,
        coordinator=coordinator or AgentRunCoordinator((TARGET,)),
        settlement=settlement,
    )


async def test_first_party_composed_http_delivers_tools_and_widget_failure_while_native_pauses(
    tmp_path: Path,
) -> None:
    fixture = PausedNativeHermesFixture()
    adapter = HermesSessionAdapter(
        api_root="http://hermes.test/",
        api_key="fixture",
        runtime_binding_id="fixture-deployment",
        settlement_timeout_seconds=0.02,
        client=httpx.AsyncClient(transport=httpx.MockTransport(fixture.handle)),
    )
    database = SqliteDatabase(tmp_path / "composed-http.db")
    await database.migrate()

    class UnusedCompatibilityRuntime:
        profile = TARGET.runtime_profile

        async def run(self, command: StartRunCommand) -> AsyncGenerator[AgentAdapterEvent, None]:
            raise AssertionError("First-party HTTP must use native execution")
            yield AgentAdapterCompleted()

    composition = await compose_host_capabilities(
        TARGET,
        UnusedCompatibilityRuntime(),
        SqliteAgentSessionRepository(database.session_factory),
        native=NativeSessionPorts(
            binding_id="fixture-deployment",
            catalog=adapter,
            history=adapter,
            execution=adapter,
            control=adapter,
        ),
        mcp_apps_enabled=True,
    )
    assert composition.sessions is not None and composition.session_events is not None
    session = await composition.sessions.create_session(CreateAgentSessionCommand())
    observer = composition.bridge_observer_factory.create("private-gateway-session", "fixture")
    assert observer is not None
    await observer.observe(
        ToolsPublished(
            session_key="private-gateway-session",
            tools=(ToolDescriptor(name="inspect", ui_resource_uri="ui://fixture/inspect"),),
        )
    )
    probe = HostAsgiProbe(
        create_app(
            Mock(spec=GatewaySessionCoordinator),
            agent_sessions=composition.sessions,
            host_session_events=composition.session_events,
        )
    )
    try:
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(probe.run, f"/api/v1/host/sessions/{session.session_id}/runs")
            with anyio.fail_after(1):
                await probe.first_frame.wait()
                await fixture.paused.wait()
            await observer.observe(
                ToolCallStarted(
                    session_key="private-gateway-session",
                    operation_key="private-operation",
                    tool_name="inspect",
                    arguments={"value": 42},
                )
            )
            await observer.observe(
                ToolCallCompleted(
                    session_key="private-gateway-session",
                    operation_key="private-operation",
                    result=ToolCallResult(
                        content=({"type": "text", "text": "Tool result"},),
                        structured_content={"value": 42},
                    ),
                )
            )
            await observer.observe(
                BridgeErrorRaised(
                    session_key="private-gateway-session",
                    operation_key="private-operation",
                    operation="application_resource_load",
                    failure=BridgeFailure(
                        code=BridgeFailureCode.UPSTREAM_PROTOCOL,
                        message="private-runtime-url-and-secret",
                    ),
                )
            )
            with anyio.fail_after(1):
                received = await probe.wait_events(4)
            assert [event.event.kind for event in received] == [
                "run.started",
                "tool.started",
                "tool.completed",
                "widget.failed",
            ]
            started, result, widget = received[1].event, received[2].event, received[3].event
            assert (
                started.kind == "tool.started"
                and result.kind == "tool.completed"
                and widget.kind == "widget.failed"
            )
            assert (
                started.tool_invocation_id == result.tool_invocation_id == widget.tool_invocation_id
            )
            assert (
                result.result.structured_content
                == widget.tool_result.structured_content
                == {"value": 42}
            )
            assert result.result.content == ({"type": "text", "text": "Tool result"},)
            assert not fixture.resume.is_set() and not probe.finished.is_set()
            fixture.terminal = True
            fixture.resume.set()
            with anyio.fail_after(1):
                await probe.finished.wait()
        received = probe.events()
        assert received[-1].event.kind == "run.completed"
        assert [event.sequence for event in received] == list(range(1, len(received) + 1))
        assert all(
            event.session_id == session.session_id and event.run_id == received[0].run_id
            for event in received
        )
        wire = "".join(event.model_dump_json() for event in received)
        for private in (
            "session_key",
            "operation_key",
            "private-gateway-session",
            "private-operation",
            "private-runtime-url-and-secret",
            "remote_session_id",
            "remote_run_id",
        ):
            assert private not in wire
        assert (
            await SqliteAgentSessionRepository(database.session_factory).get_unsettled_run(
                TARGET.target_id
            )
            is None
        )
        assert probe.error is None and fixture.stream_closed.is_set()
    finally:
        await adapter.close()
        await database.close()


async def test_native_sessions_switch_reopen_and_continue_without_local_transcript(
    tmp_path: Path,
) -> None:
    fixture = NativeHermesFixture()
    adapter = HermesSessionAdapter(
        api_root="http://hermes.test/",
        api_key="fixture-key",
        runtime_binding_id="fixture-deployment",
        client=httpx.AsyncClient(transport=httpx.MockTransport(fixture.handle)),
    )
    path = tmp_path / "sessions.db"
    database = SqliteDatabase(path)
    await database.migrate()
    try:
        service = session_service(database, adapter)
        first = await service.create_session(CreateAgentSessionCommand())
        second = await service.create_session(CreateAgentSessionCommand())
        for session, text in ((first, "First"), (second, "Second")):
            events = [
                event
                async for event in service.run_session(
                    StartSessionRunCommand(session_id=session.session_id, input_text=text)
                )
            ]
            assert events[-1].kind == "session_adapter.completed"
        first_content = (
            (await service.read_history(first.session_id, HistoryPageQuery()))
            .messages[0]
            .content[0]
        )
        second_content = (
            (await service.read_history(second.session_id, HistoryPageQuery()))
            .messages[0]
            .content[0]
        )
        assert first_content.kind == "text"
        assert second_content.kind == "text"
        assert first_content.text == "First"
        assert second_content.text == "Second"
        assert fixture.inputs == [{"message": "First"}, {"message": "Second"}]
        fixture.resumed = True
        async for _event in service.run_session(
            StartSessionRunCommand(session_id=first.session_id, input_text="Continue")
        ):
            pass
        resumed = await service.reopen_session(first.session_id)
        assert resumed.session_id == first.session_id
        assert resumed.runtime_session.remote_session_id == "api_1_resumed"
    finally:
        await database.close()
    reopened = SqliteDatabase(path)
    try:
        service = session_service(reopened, adapter)
        assert (
            await service.reopen_session(first.session_id)
        ).runtime_session == resumed.runtime_session
        assert len(await service.list_sessions()) == 2
        fixture.messages.pop(second.runtime_session.remote_session_id)
        with pytest.raises(AgentSessionError) as missing:
            await service.reopen_session(second.session_id)
        assert missing.value.code == "remote_session_not_found"
        with pytest.raises(AgentSessionError) as changed:
            await session_service(reopened, adapter, binding_id="other").read_history(
                first.session_id, HistoryPageQuery()
            )
        assert changed.value.code == "runtime_binding_changed"
    finally:
        await reopened.close()
        await adapter.close()


async def test_unresolved_native_execution_blocks_restart_until_remote_terminal(
    tmp_path: Path,
) -> None:
    fixture = NativeHermesFixture()
    fixture.terminal = False
    adapter = HermesSessionAdapter(
        api_root="http://hermes.test/",
        api_key="fixture-key",
        runtime_binding_id="fixture-deployment",
        settlement_timeout_seconds=0.02,
        client=httpx.AsyncClient(transport=httpx.MockTransport(fixture.handle)),
    )
    path = tmp_path / "sessions.db"
    database = SqliteDatabase(path)
    await database.migrate()
    try:
        service = session_service(database, adapter)
        session = await service.create_session(CreateAgentSessionCommand())
        command = StartSessionRunCommand(session_id=session.session_id, input_text="Pause")
        stream = service.run_session(command)
        await anext(stream)
        assert not await service.reconcile_run()
        with pytest.raises(AgentSessionError) as unknown:
            await stream.aclose()
        assert unknown.value.code == "run_state_unknown"
        assert await service.coordinator.active_run_id(TARGET.target_id) == command.run_id
    finally:
        await database.close()
    reopened = SqliteDatabase(path)
    try:
        service = session_service(reopened, adapter)
        await service.restore_ownership()
        assert await service.coordinator.active_run_id(TARGET.target_id) == command.run_id
        assert not await service.reconcile_run()
        with pytest.raises(AgentSessionError) as blocked:
            await anext(
                service.run_session(
                    StartSessionRunCommand(session_id=session.session_id, input_text="Overlap")
                )
            )
        assert blocked.value.code == "run_state_unknown"
        assert fixture.inputs == [{"message": "Pause"}]
        fixture.terminal = True
        assert await service.reconcile_run()
        assert await service.coordinator.active_run_id(TARGET.target_id) is None
    finally:
        await reopened.close()
        await adapter.close()


async def test_native_binding_and_unsettled_ownership_survive_database_reopen(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sessions.db"
    database = SqliteDatabase(path)
    await database.migrate()
    session = AgentSessionRecord(
        target_id="fixture-target",
        runtime_session=RuntimeSessionReference(
            runtime_binding_id="fixture-deployment", remote_session_id="api_fixture"
        ),
        created_at=datetime.now(timezone.utc),
    )
    run_id = uuid4()
    try:
        repository = SqliteAgentSessionRepository(database.session_factory)
        await repository.add(session)
        assert await repository.claim_run(session, run_id)
        assert not await repository.claim_run(session, uuid4())
        await repository.record_runtime_run(
            session.target_id,
            run_id,
            RuntimeRunHandle(runtime_binding_id="fixture-deployment", remote_run_id="run_fixture"),
        )
    finally:
        await database.close()
    reopened = SqliteDatabase(path)
    try:
        repository = SqliteAgentSessionRepository(reopened.session_factory)
        assert await repository.get(session.session_id) == session
        pending = await repository.get_unsettled_run(session.target_id)
        assert pending is not None and pending.run_id == run_id
        assert pending.remote_run_id == "run_fixture"
        assert await repository.list_sessions(target_id=session.target_id, limit=10, offset=0) == (
            session,
        )
        replacement = session.runtime_session.model_copy(
            update={"remote_session_id": "api_resumed"}
        )
        assert await repository.update_runtime_session(
            session.session_id, expected=session.runtime_session, replacement=replacement
        )
        assert not await repository.update_runtime_session(
            session.session_id, expected=session.runtime_session, replacement=replacement
        )
        with pytest.raises(ValueError):
            await repository.update_runtime_session(
                session.session_id,
                expected=replacement,
                replacement=replacement.model_copy(update={"runtime_binding_id": "other"}),
            )
        await repository.release_run(session.target_id, run_id)
        assert await repository.get_unsettled_run(session.target_id) is None
    finally:
        await reopened.close()


@pytest.mark.parametrize("outcome", ["unknown", "failure", "success", "early_close"])
async def test_native_terminal_and_durable_release_depend_on_host_settlement(
    tmp_path: Path, outcome: str
) -> None:
    fixture = NativeHermesFixture()
    adapter = HermesSessionAdapter(
        api_root="http://hermes.test/",
        api_key="fixture",
        runtime_binding_id="fixture-deployment",
        client=httpx.AsyncClient(transport=httpx.MockTransport(fixture.handle)),
    )
    database = SqliteDatabase(tmp_path / "settling.db")
    await database.migrate()
    settlement = HostRunSettlement(timeout_seconds=0.01)
    service = session_service(database, adapter, settlement=settlement)
    repository = SqliteAgentSessionRepository(database.session_factory)
    try:
        session = await service.create_session(CreateAgentSessionCommand())
        command = StartSessionRunCommand(session_id=session.session_id, input_text="Fixture")
        stream = service.run_session(command)
        await anext(stream)
        await settlement.start(command.run_id, "gateway-session", "operation")
        if outcome == "failure":
            await settlement.fail(command.run_id)
            await settlement.complete(command.run_id, "gateway-session", "operation")
        elif outcome == "success":
            await settlement.complete(command.run_id, "gateway-session", "operation")
        if outcome == "success":
            events = [event async for event in stream]
            assert events[-1].kind == "session_adapter.completed"
        else:
            with pytest.raises(AgentSessionError) as error:
                with anyio.fail_after(0.3):
                    if outcome == "early_close":
                        await stream.aclose()
                    else:
                        async for event in stream:
                            assert event.kind != "session_adapter.completed"
            assert error.value.code == (
                "run_state_unknown"
                if outcome in {"unknown", "early_close"}
                else "runtime_contract_error"
            )
        if outcome in {"unknown", "early_close"}:
            pending = await repository.get_unsettled_run(TARGET.target_id)
            assert pending is not None and pending.run_id == command.run_id
            assert await service.coordinator.active_run_id(TARGET.target_id) == command.run_id
            with pytest.raises(AgentSessionError):
                await service.reconcile_run()
            await settlement.complete(command.run_id, "gateway-session", "operation")
            assert await service.reconcile_run()
        assert await repository.get_unsettled_run(TARGET.target_id) is None
        assert await service.coordinator.active_run_id(TARGET.target_id) is None
    finally:
        await adapter.close()
        await database.close()


@pytest.mark.parametrize("early_close", [False, True])
async def test_native_composed_stream_presents_activity_during_provider_pause_and_settles(
    tmp_path: Path, early_close: bool
) -> None:
    fixture = PausedNativeHermesFixture()
    adapter = HermesSessionAdapter(
        api_root="http://hermes.test/",
        api_key="fixture",
        runtime_binding_id="fixture-deployment",
        settlement_timeout_seconds=0.02,
        client=httpx.AsyncClient(transport=httpx.MockTransport(fixture.handle)),
    )
    database = SqliteDatabase(tmp_path / "presentation.db")
    await database.migrate()
    repository = SqliteAgentSessionRepository(database.session_factory)

    class UnusedCompatibilityRuntime:
        profile = TARGET.runtime_profile

        async def run(self, command: StartRunCommand) -> AsyncGenerator[AgentAdapterEvent, None]:
            raise AssertionError("Native presentation must not invoke compatibility runtime")
            yield AgentAdapterCompleted()

    composition = await compose_host_capabilities(
        TARGET,
        UnusedCompatibilityRuntime(),
        repository,
        native=NativeSessionPorts(
            binding_id="fixture-deployment",
            catalog=adapter,
            history=adapter,
            execution=adapter,
            control=adapter,
        ),
        mcp_apps_enabled=True,
    )
    assert composition.sessions is not None and composition.session_events is not None
    session = await composition.sessions.create_session(CreateAgentSessionCommand())
    command = StartSessionRunCommand(session_id=session.session_id, input_text="New input")
    observer = composition.bridge_observer_factory.create("gateway-session", "fixture")
    assert observer is not None
    await observer.observe(
        ToolsPublished(
            session_key="gateway-session",
            tools=(ToolDescriptor(name="inspect", ui_resource_uri="ui://fixture/inspect"),),
        )
    )
    stream = composition.session_events.run_events(command)
    received = []
    try:
        received.append(await anext(stream))
        assert isinstance(received[0], HostAgentEvent) and received[0].event.kind == "run.started"
        delivered = anyio.Event()

        async def receive_activity() -> None:
            for _index in range(3):
                received.append(await anext(stream))
            delivered.set()

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(receive_activity)
            await fixture.paused.wait()
            await observer.observe(
                ToolCallStarted(
                    session_key="gateway-session",
                    operation_key="operation",
                    tool_name="inspect",
                    arguments={"value": 42},
                )
            )
            await observer.observe(
                ToolCallCompleted(
                    session_key="gateway-session",
                    operation_key="operation",
                    result=ToolCallResult(structured_content={"value": 42}),
                )
            )
            await observer.observe(
                BridgeErrorRaised(
                    session_key="gateway-session",
                    operation_key="operation",
                    operation="application_resource_load",
                    failure=BridgeFailure(
                        code=BridgeFailureCode.UPSTREAM_PROTOCOL, message="widget unavailable"
                    ),
                )
            )
            with anyio.fail_after(0.5):
                await delivered.wait()
        assert isinstance(received[1], HostToolEvent) and isinstance(
            received[1].event, ToolInvocationStarted
        )
        assert isinstance(received[2], HostToolEvent) and isinstance(
            received[2].event, ToolInvocationCompleted
        )
        assert (
            isinstance(received[3], HostWidgetEvent) and received[3].event.kind == "widget.failed"
        )
        assert received[3].tool_invocation_id == received[1].event.tool_invocation_id
        assert received[2].event.result.structured_content == {"value": 42}
        assert not fixture.resume.is_set()
        assert all(event.session_id == session.session_id for event in received)
        assert all("remote_run_id" not in event.model_dump_json() for event in received)
        if early_close:
            with pytest.raises(AgentSessionError) as unknown:
                with anyio.fail_after(0.3):
                    await stream.aclose()
            assert unknown.value.code == "run_state_unknown"
            pending = await repository.get_unsettled_run(TARGET.target_id)
            assert pending is not None and pending.run_id == command.run_id
            assert (
                await composition.sessions.coordinator.active_run_id(TARGET.target_id)
                == command.run_id
            )
            fixture.terminal = True
            assert await composition.sessions.reconcile_run()
        else:
            fixture.terminal = True
            fixture.resume.set()
            received.extend([event async for event in stream])
            assert (
                isinstance(received[-1], HostAgentEvent)
                and received[-1].event.kind == "run.completed"
            )
            assert [event.sequence for event in received] == list(range(1, len(received) + 1))
            assert await repository.get_unsettled_run(TARGET.target_id) is None
        assert fixture.stream_closed.is_set()
        assert await composition.sessions.coordinator.active_run_id(TARGET.target_id) is None
    finally:
        await stream.aclose()
        await adapter.close()
        await database.close()
