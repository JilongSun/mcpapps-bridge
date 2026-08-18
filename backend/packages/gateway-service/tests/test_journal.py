from __future__ import annotations

import pytest
from mcp_bridge_core import (
    BridgeFailure,
    BridgeFailureCode,
    BridgeSessionStarted,
    ToolCallStarted,
    UpstreamIdentity,
)

from mcp_gateway_service import (
    JournalBridgeObserver,
    SessionJournalEvent,
    SessionStartedJournalEvent,
    ToolCallStartedJournalEvent,
)


class RecordingJournal:
    def __init__(self) -> None:
        self.events: list[SessionJournalEvent] = []

    async def append(self, event: SessionJournalEvent) -> None:
        self.events.append(event)


async def test_journal_observer_translates_core_observations() -> None:
    journal = RecordingJournal()
    observer = JournalBridgeObserver("session-1", journal)

    await observer.observe(
        BridgeSessionStarted(
            session_key="session-1",
            identity=UpstreamIdentity(server_name="fixture"),
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

    started = journal.events[0]
    assert isinstance(started, SessionStartedJournalEvent)
    assert started.identity.server_name == "fixture"
    tool_call = journal.events[1]
    assert isinstance(tool_call, ToolCallStartedJournalEvent)
    assert tool_call.operation_key == "operation-1"


async def test_journal_observer_rejects_cross_session_observations() -> None:
    journal = RecordingJournal()
    observer = JournalBridgeObserver("session-1", journal)

    with pytest.raises(ValueError, match="observation session mismatch"):
        await observer.observe(
            ToolCallStarted(
                session_key="session-2",
                operation_key="operation-1",
                tool_name="inspect",
            )
        )

    assert journal.events == []


def test_failure_contract_is_available_to_application_journal() -> None:
    failure = BridgeFailure(
        code=BridgeFailureCode.UPSTREAM_TRANSPORT,
        message="upstream unavailable",
        retryable=True,
    )
    assert failure.code is BridgeFailureCode.UPSTREAM_TRANSPORT
