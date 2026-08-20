from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

from mcp_bridge_core import (
    BindingAvailabilityStatus,
    BindingAvailabilityChanged,
    BridgeFailure,
    BridgeFailureCode,
    ToolCallCompleted,
    ToolCallStarted,
    ToolDescriptor,
    ToolsPublished,
)
from mcp_gateway_service import (
    BridgeSessionStore,
    BridgeSessionStoreJournal,
    EndpointBindingRevision,
    EndpointMode,
    EndpointTopologyRevision,
    JournalBridgeObserver,
    StdioConnection,
    UpstreamRevision,
)


async def test_journal_adapter_preserves_operation_and_binding_revision_keys() -> None:
    upstream = UpstreamRevision(
        server_id=uuid4(),
        slug="fixture",
        display_name="Fixture",
        connection=StdioConnection(command="fixture-server"),
    )
    binding = EndpointBindingRevision(namespace="fixture", upstream=upstream)
    revision = EndpointTopologyRevision(
        endpoint_id=uuid4(),
        slug="all",
        display_name="All Tools",
        mode=EndpointMode.AGGREGATE,
        bindings=(binding,),
    )
    store = cast(BridgeSessionStore, AsyncMock(spec=BridgeSessionStore))
    journal = BridgeSessionStoreJournal("session-1", revision, store)
    observer = JournalBridgeObserver("session-1", journal)

    await observer.observe(
        ToolsPublished(
            session_key="session-1",
            tools=(ToolDescriptor(name="fixture__inspect"),),
        )
    )
    await observer.observe(
        ToolCallStarted(
            session_key="session-1",
            operation_key="operation-1",
            tool_name="fixture__inspect",
            arguments={"depth": 2},
        )
    )
    failure = BridgeFailure(
        code=BridgeFailureCode.UPSTREAM_TRANSPORT,
        message="upstream unavailable",
        retryable=True,
        binding_key=str(binding.binding_revision_id),
    )
    await observer.observe(
        ToolCallCompleted(
            session_key="session-1",
            operation_key="operation-1",
            failure=failure,
        )
    )
    await observer.observe(
        BindingAvailabilityChanged(
            session_key="session-1",
            binding_key=str(binding.binding_revision_id),
            status=BindingAvailabilityStatus.FAILED,
            failure=failure,
        )
    )

    register_tools = cast(AsyncMock, store.register_tools)
    start_tool_call = cast(AsyncMock, store.start_tool_call)
    complete_tool_call = cast(AsyncMock, store.complete_tool_call)
    set_upstream_availability = cast(AsyncMock, store.set_upstream_availability)
    register_tools.assert_awaited_once()
    start_tool_call.assert_awaited_once_with(
        "fixture__inspect",
        {"depth": 2},
        call_id="operation-1",
    )
    completed = complete_tool_call.await_args
    assert completed is not None
    assert completed.args[0] == "operation-1"
    assert completed.args[1].is_error is True
    assert completed.kwargs == {"failed": True}
    availability_call = set_upstream_availability.await_args
    assert availability_call is not None
    availability = availability_call.args[0][0]
    assert availability.binding_revision_id == str(binding.binding_revision_id)
    assert availability.upstream_revision_id == str(upstream.revision_id)
    assert availability.error_message == "upstream unavailable"
