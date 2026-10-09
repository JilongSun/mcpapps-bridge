from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import json

import httpx
import pytest
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

    async def handle(self, request: httpx.Request) -> httpx.Response:
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
