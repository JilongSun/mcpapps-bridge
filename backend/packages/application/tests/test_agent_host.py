from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError
from mabrid.bridge import ToolCallStarted
from mabrid.application.agent_host import (
    AgentHostCapabilityService,
    RuntimeCapabilityObservation,
    RuntimeSupport,
    AgentAdapterCompleted,
    AgentAdapterEvent,
    AgentAdapterTextDelta,
    AgentCapability,
    AgentEndpointAssignment,
    AgentHostService,
    AgentOperationAttributionObserverFactory,
    AgentMessage,
    AgentRunConflictError,
    AgentRunCoordinator,
    AgentRunError,
    AgentRuntime,
    AgentRuntimeInterface,
    AgentRuntimeProfile,
    AgentTarget,
    AgentTargetConflictError,
    InMemoryOperationRunAttributionRegistry,
    StartRunCommand,
    TokenUsage,
)
from mabrid.application.agent_host.contracts.session import (
    AgentHistoryMessage,
    AgentHistoryPage,
    AgentSessionRecord,
    HistoryPageQuery,
    HistoryText,
    HistoryToolCall,
    HistoryUnsupportedContent,
    RuntimeRunHandle,
    RuntimeRunState,
    RuntimeSessionReference,
    RuntimeStopReceipt,
    StartSessionRunCommand,
)


@pytest.mark.parametrize(
    "mode",
    [
        "verified",
        "unknown",
        "unsupported",
        "outage",
        "compatibility_only",
        "disabled",
        "widgets_disabled",
    ],
)
async def test_effective_capabilities_separate_local_selection_and_remote_evidence(
    mode: str,
) -> None:
    class Probe:
        calls = 0

        async def inspect_capabilities(self) -> RuntimeCapabilityObservation:
            self.calls += 1
            support = (
                True
                if mode not in {"unknown", "unsupported", "outage"}
                else False
                if mode == "unsupported"
                else None
            )
            return RuntimeCapabilityObservation(
                availability="unavailable" if mode == "outage" else "available",
                reason="runtime_unavailable" if mode == "outage" else "discovery_verified",
                support=RuntimeSupport(
                    session_create=support,
                    session_reopen=support,
                    session_history=support,
                    session_streaming=support,
                    run_status=support,
                    run_stop=support,
                    compatibility_streaming=True,
                ),
            )

    native, compatibility = Probe(), Probe()
    service = AgentHostCapabilityService(
        target_id=None if mode == "disabled" else "fixture",
        native_probe=None if mode == "compatibility_only" else native,
        compatibility_probe=compatibility,
        mcp_apps_enabled=mode != "widgets_disabled",
    )
    snapshot = await service.snapshot()
    assert snapshot.enabled == (mode != "disabled")
    expected = {
        "verified": "available",
        "unknown": "unknown",
        "unsupported": "unsupported",
        "outage": "unavailable",
        "compatibility_only": "disabled",
        "disabled": "disabled",
        "widgets_disabled": "available",
    }[mode]
    for feature in (
        snapshot.features.session_create,
        snapshot.features.session_history,
        snapshot.features.session_streaming,
        snapshot.features.run_cancel,
        snapshot.features.run_reconcile,
        snapshot.features.tool_activity,
    ):
        assert feature.availability == expected and feature.implemented
    assert snapshot.features.widgets.availability == (
        "disabled" if mode == "widgets_disabled" else expected
    )
    assert snapshot.features.session_list.availability == (
        "disabled" if mode in {"disabled", "compatibility_only"} else "available"
    )
    assert snapshot.features.compatibility_streaming.availability == (
        "disabled" if mode == "disabled" else "unavailable" if mode == "outage" else "available"
    )
    for feature in (
        snapshot.features.host_actions,
        snapshot.features.event_replay,
        snapshot.features.remote_session_import,
    ):
        assert (
            feature.availability == "unsupported"
            and not feature.implemented
            and not feature.enabled
        )
    assert native.calls == (0 if mode in {"disabled", "compatibility_only"} else 1)
    assert compatibility.calls == (0 if mode == "disabled" else 1)
    assert snapshot.max_concurrent_runs == 1


async def test_capability_probes_are_bounded_joined_and_not_cached() -> None:
    import anyio

    class Probe:
        calls = 0
        closed = False

        async def inspect_capabilities(self) -> RuntimeCapabilityObservation:
            self.calls += 1
            if self.calls == 1:
                return RuntimeCapabilityObservation(
                    availability="available",
                    reason="discovery_verified",
                    support=RuntimeSupport(session_streaming=True, session_reopen=True),
                )
            try:
                await anyio.Event().wait()
                raise AssertionError("unreachable")
            finally:
                self.closed = True

    native, compatibility = Probe(), Probe()
    service = AgentHostCapabilityService(
        target_id="fixture",
        native_probe=native,
        compatibility_probe=compatibility,
        probe_timeout_seconds=0.02,
    )
    assert (await service.snapshot()).features.session_streaming.availability == "available"
    with anyio.fail_after(0.3):
        snapshot = await service.snapshot()
    assert snapshot.native_runtime is not None and snapshot.compatibility_runtime is not None
    assert (
        snapshot.native_runtime.reason == snapshot.compatibility_runtime.reason == "probe_timeout"
    )
    assert snapshot.features.session_streaming.availability == "unavailable"
    assert snapshot.features.session_streaming.remote_support is None
    assert native.closed and compatibility.closed


def test_session_contract_separates_binding_history_and_new_input() -> None:
    session = AgentSessionRecord(
        target_id="fixture-target",
        runtime_session=RuntimeSessionReference(
            runtime_binding_id="fixture-deployment",
            remote_session_id="api_remote-session",
        ),
        created_at=datetime.now(timezone.utc),
    )
    command = StartSessionRunCommand(session_id=session.session_id, input_text="Continue")
    history = AgentHistoryPage(
        session_id=session.session_id,
        query=HistoryPageQuery(),
        messages=(
            AgentHistoryMessage(
                message_id="remote-message-1",
                role="user",
                content=(HistoryText(text="Earlier input"),),
            ),
            AgentHistoryMessage(
                message_id="remote-message-2",
                role="assistant",
                content=(HistoryUnsupportedContent(content_type="image"),),
            ),
        ),
    )

    assert command.session_id == session.session_id
    assert set(command.model_dump()) == {"run_id", "session_id", "input_text"}
    assert "messages" not in session.model_dump()
    assert "remote_session_id" not in history.model_dump_json()
    assert history.has_more is None
    assert history.messages[1].content[0].kind == "unsupported"
    assert AgentHistoryPage.model_validate_json(history.model_dump_json()) == history


async def test_enabled_interfaces_without_discovery_are_unknown_not_disabled() -> None:
    snapshot = await AgentHostCapabilityService(
        target_id="fixture", native_enabled=True, compatibility_enabled=True
    ).snapshot()
    assert snapshot.features.session_list.availability == "available"
    assert (
        snapshot.features.session_streaming.enabled
        and snapshot.features.session_streaming.availability == "unknown"
    )
    assert (
        snapshot.features.compatibility_streaming.enabled
        and snapshot.features.compatibility_streaming.availability == "unknown"
    )
    assert snapshot.native_runtime is None and snapshot.compatibility_runtime is None


async def test_streaming_support_does_not_imply_remote_stop_or_replay() -> None:
    class Probe:
        async def inspect_capabilities(self) -> RuntimeCapabilityObservation:
            return RuntimeCapabilityObservation(
                availability="available",
                reason="discovery_verified",
                support=RuntimeSupport(
                    session_reopen=True, session_streaming=True, run_stop=False, run_status=None
                ),
            )

    snapshot = await AgentHostCapabilityService(
        target_id="fixture", native_probe=Probe()
    ).snapshot()
    assert snapshot.features.session_streaming.availability == "available"
    assert snapshot.features.run_cancel.remote_support is False
    assert snapshot.features.run_cancel.availability == "unsupported"
    assert snapshot.features.run_reconcile.availability == "unknown"
    assert snapshot.features.event_replay.availability == "unsupported"


async def test_capability_request_cancellation_propagates_and_joins_both_probes() -> None:
    import anyio

    class Probe:
        def __init__(self) -> None:
            self.started = anyio.Event()
            self.closed = False

        async def inspect_capabilities(self) -> RuntimeCapabilityObservation:
            self.started.set()
            try:
                await anyio.Event().wait()
                raise AssertionError("unreachable")
            finally:
                self.closed = True

    native, compatibility = Probe(), Probe()
    service = AgentHostCapabilityService(
        target_id="fixture", native_probe=native, compatibility_probe=compatibility
    )
    returned = False

    async def read() -> None:
        nonlocal returned
        await service.snapshot()
        returned = True

    with anyio.fail_after(0.5):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(read)
            await native.started.wait()
            await compatibility.started.wait()
            tasks.cancel_scope.cancel()
    assert native.closed and compatibility.closed and not returned


@pytest.mark.parametrize(
    "fields",
    [
        {"limit": 0},
        {"limit": 501},
        {"offset": -1},
        {"order": "provider-default"},
    ],
)
def test_history_query_rejects_ambiguous_or_unbounded_pagination(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        HistoryPageQuery.model_validate(fields)


def test_session_run_rejects_transcript_replay_and_empty_input() -> None:
    with pytest.raises(ValidationError):
        StartSessionRunCommand.model_validate(
            {"session_id": str(uuid4()), "input_text": "Continue", "messages": []}
        )
    with pytest.raises(ValidationError):
        StartSessionRunCommand(session_id=uuid4(), input_text="")
    with pytest.raises(ValidationError):
        StartSessionRunCommand(session_id=uuid4(), input_text=" \n\t")


def test_history_preserves_tool_calls_without_turning_them_into_new_input() -> None:
    message = AgentHistoryMessage(
        message_id="remote-message-3",
        role="assistant",
        content=(
            HistoryText(text="Searching"),
            HistoryToolCall(
                tool_call_id="call_1",
                tool_name="fixture__search",
                arguments={"query": "example", "limit": 2},
            ),
        ),
    )
    assert AgentHistoryMessage.model_validate_json(message.model_dump_json()) == message
    assert message.content[1].kind == "tool_call"


@pytest.mark.parametrize("state", ["queued", "running", "stopping", "unknown"])
def test_stop_receipt_and_nonterminal_state_do_not_confirm_remote_exit(state: str) -> None:
    handle = RuntimeRunHandle(runtime_binding_id="fixture-deployment", remote_run_id="run_1")
    receipt = RuntimeStopReceipt(handle=handle, accepted=True)
    snapshot = RuntimeRunState.model_validate({"handle": handle, "state": state})

    assert receipt.accepted is True
    assert snapshot.is_terminal is False


@pytest.mark.parametrize("state", ["completed", "failed", "cancelled"])
def test_runtime_terminal_state_is_explicit(state: str) -> None:
    handle = RuntimeRunHandle(runtime_binding_id="fixture-deployment", remote_run_id="run_1")
    snapshot = RuntimeRunState.model_validate({"handle": handle, "state": state})
    assert snapshot.is_terminal is True


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


class SuccessfulAdapter:
    @property
    def profile(self) -> AgentRuntimeProfile:
        return PROFILE

    async def run(self, command: StartRunCommand) -> AsyncGenerator[AgentAdapterEvent, None]:
        assert command.model == TARGET.target_id
        yield AgentAdapterTextDelta(delta="Hello")
        yield AgentAdapterTextDelta(delta=" world")
        yield AgentAdapterCompleted(
            finish_reason="stop",
            usage=TokenUsage(input_tokens=3, output_tokens=2),
        )


class FailingAdapter:
    @property
    def profile(self) -> AgentRuntimeProfile:
        return PROFILE

    async def run(self, command: StartRunCommand) -> AsyncGenerator[AgentAdapterEvent, None]:
        raise RuntimeError(f"Provider unavailable for {command.model}")
        yield


def _command() -> StartRunCommand:
    return StartRunCommand(
        model="caller-selected-model",
        messages=(AgentMessage(role="user", content="Say hello"),),
    )


def _service(runtime: AgentRuntime) -> AgentHostService:
    return AgentHostService(TARGET, runtime, AgentRunCoordinator((TARGET,)))


async def test_agent_host_emits_provider_neutral_ordered_events() -> None:
    service = _service(SuccessfulAdapter())

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
    assert completed.result.model == TARGET.target_id
    assert completed.result.output_text == "Hello world"
    assert completed.result.usage.total_tokens == 5


async def test_agent_host_complete_returns_the_terminal_result() -> None:
    service = _service(SuccessfulAdapter())

    result = await service.complete(_command())

    assert result.output_text == "Hello world"
    assert result.finish_reason == "stop"
    assert await service.coordinator.active_run_id(TARGET.target_id) is None


async def test_agent_run_stays_active_until_terminal_event_is_consumed() -> None:
    service = _service(SuccessfulAdapter())
    command = _command()
    stream = service.run_events(command)

    terminal = None
    while terminal is None:
        event = await anext(stream)
        if event.kind == "run.completed":
            terminal = event

    assert await service.coordinator.active_run_id(TARGET.target_id) == command.run_id
    await stream.aclose()
    assert await service.coordinator.active_run_id(TARGET.target_id) is None


async def test_closing_run_releases_outbound_runtime_stream() -> None:
    class ClosableAdapter(SuccessfulAdapter):
        closed = False

        async def run(self, command: StartRunCommand) -> AsyncGenerator[AgentAdapterEvent, None]:
            try:
                yield AgentAdapterTextDelta(delta="partial")
                yield AgentAdapterCompleted()
            finally:
                self.closed = True

    adapter = ClosableAdapter()
    service = _service(adapter)
    stream = service.run_events(_command())
    assert (await anext(stream)).kind == "run.started"
    assert (await anext(stream)).kind == "assistant.text.delta"

    await stream.aclose()

    assert adapter.closed is True
    assert await service.coordinator.active_run_id(TARGET.target_id) is None


async def test_agent_host_normalizes_adapter_failure() -> None:
    adapter: AgentRuntime = FailingAdapter()
    service = _service(adapter)

    events = [event async for event in service.run_events(_command())]

    assert [event.kind for event in events] == ["run.started", "run.failed"]
    assert events[-1].sequence == 2
    assert await service.coordinator.active_run_id(TARGET.target_id) is None
    with pytest.raises(AgentRunError, match="Provider unavailable for fixture-target"):
        await service.complete(_command())


async def test_agent_host_advertises_only_its_canonical_target() -> None:
    service = _service(SuccessfulAdapter())

    models = await service.list_models()

    assert [(model.model_id, model.owned_by) for model in models] == [("fixture-target", "fixture")]
    assert service.runtime_profile == PROFILE
    assert service.target.endpoint_assignment.endpoint_slug == "fixture-endpoint"


def test_agent_host_rejects_a_runtime_that_does_not_match_the_target() -> None:
    mismatched_profile = PROFILE.model_copy(update={"integration_kind": "other-fixture"})

    class MismatchedRuntime(SuccessfulAdapter):
        @property
        def profile(self) -> AgentRuntimeProfile:
            return mismatched_profile

    with pytest.raises(ValueError, match="does not match Agent Target"):
        _service(MismatchedRuntime())


def test_run_coordinator_rejects_shared_endpoint_assignment() -> None:
    conflicting_target = TARGET.model_copy(update={"target_id": "other-target"})

    with pytest.raises(AgentTargetConflictError, match="assigned to both Agent Targets"):
        AgentRunCoordinator((TARGET, conflicting_target))


async def test_agent_host_rejects_a_second_active_run() -> None:
    service = _service(SuccessfulAdapter())
    first_run = service.run_events(_command())
    started = await anext(first_run)

    assert started.kind == "run.started"
    assert await service.coordinator.active_run_id(TARGET.target_id) == started.run_id
    with pytest.raises(AgentRunConflictError, match="already has active Run"):
        await anext(service.run_events(_command()))

    await first_run.aclose()
    assert await service.coordinator.active_run_id(TARGET.target_id) is None
    events = [event async for event in service.run_events(_command())]
    assert events[-1].kind == "run.completed"


async def test_tool_operation_captures_the_active_run_at_start() -> None:
    coordinator = AgentRunCoordinator((TARGET,))
    registry = InMemoryOperationRunAttributionRegistry()
    observer = AgentOperationAttributionObserverFactory(coordinator, registry).create(
        "session-1",
        "fixture-endpoint",
    )
    assert observer is not None
    run_id = _command().run_id
    await coordinator.start_run(TARGET.target_id, run_id)

    await observer.observe(
        ToolCallStarted(
            session_key="session-1",
            operation_key="operation-1",
            tool_name="inspect",
        )
    )
    await coordinator.finish_run(TARGET.target_id, run_id)

    attribution = await registry.get("session-1", "operation-1")
    assert attribution is not None
    assert attribution.run_id == run_id
    assert attribution.target_id == TARGET.target_id


async def test_tool_operation_without_an_active_run_is_not_attributed() -> None:
    coordinator = AgentRunCoordinator((TARGET,))
    registry = InMemoryOperationRunAttributionRegistry()
    observer = AgentOperationAttributionObserverFactory(coordinator, registry).create(
        "session-1",
        "fixture-endpoint",
    )
    assert observer is not None

    await observer.observe(
        ToolCallStarted(
            session_key="session-1",
            operation_key="operation-1",
            tool_name="inspect",
        )
    )

    assert await registry.get("session-1", "operation-1") is None


async def test_tool_operation_attribution_cannot_move_to_a_later_run() -> None:
    coordinator = AgentRunCoordinator((TARGET,))
    registry = InMemoryOperationRunAttributionRegistry()
    observer = AgentOperationAttributionObserverFactory(coordinator, registry).create(
        "session-1",
        "fixture-endpoint",
    )
    assert observer is not None
    event = ToolCallStarted(
        session_key="session-1",
        operation_key="operation-1",
        tool_name="inspect",
    )
    first_run_id = _command().run_id
    await coordinator.start_run(TARGET.target_id, first_run_id)
    await observer.observe(event)
    await coordinator.finish_run(TARGET.target_id, first_run_id)
    second_run_id = _command().run_id
    await coordinator.start_run(TARGET.target_id, second_run_id)

    with pytest.raises(ValueError, match="different Agent Run attribution"):
        await observer.observe(event)

    attribution = await registry.get("session-1", "operation-1")
    assert attribution is not None
    assert attribution.run_id == first_run_id
    await coordinator.finish_run(TARGET.target_id, second_run_id)
