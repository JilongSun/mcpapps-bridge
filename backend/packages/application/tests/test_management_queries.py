from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import AnyHttpUrl, ValidationError

from mabrid.application.gateway.inspection import (
    SequencedSessionEvent,
    SessionEventPage,
    SessionEventPageRequest,
    SessionStartedEvent,
)
from mabrid.application.gateway.sessions import (
    BridgeSessionRecord,
    SessionKeyset,
    SessionPage,
    SessionPageRequest,
)
from mabrid.application.gateway.topology import (
    ConfiguredKey,
    ManagedStreamableHttpConnection,
)


def test_management_connection_exposes_configured_keys_without_values() -> None:
    connection = ManagedStreamableHttpConnection(
        url=AnyHttpUrl("https://upstream.example.test/mcp"),
        headers=(ConfiguredKey(name="Authorization"),),
    )

    assert connection.headers[0].configured is True
    assert connection.model_dump(mode="json")["headers"] == [
        {"name": "Authorization", "configured": True}
    ]
    with pytest.raises(ValidationError):
        ConfiguredKey.model_validate(
            {"name": "Authorization", "configured": True, "value": "fixture-secret"}
        )


@pytest.mark.parametrize("limit", [0, 201])
def test_session_page_request_rejects_an_out_of_range_limit(limit: int) -> None:
    with pytest.raises(ValidationError):
        SessionPageRequest(limit=limit)


def test_session_keyset_normalizes_an_aware_datetime_to_utc() -> None:
    keyset = SessionKeyset(
        created_at=datetime(2026, 9, 15, 10, 30, tzinfo=timezone(timedelta(hours=8))),
        session_id=uuid4(),
    )

    assert keyset.created_at == datetime(2026, 9, 15, 2, 30, tzinfo=timezone.utc)


def test_session_keyset_rejects_a_naive_datetime() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        SessionKeyset(created_at=datetime(2026, 9, 15, 2, 30), session_id=uuid4())


def test_session_page_keeps_lifecycle_records_separate_from_inspection() -> None:
    record = BridgeSessionRecord(
        endpoint_id=uuid4(),
        endpoint_revision_id=uuid4(),
    )
    page = SessionPage(items=(record,))

    assert page.items == (record,)
    assert page.next_keyset is None


@pytest.mark.parametrize(("after", "limit"), [(-1, 100), (0, 0), (0, 501)])
def test_event_page_request_validates_its_bounds(after: int, limit: int) -> None:
    with pytest.raises(ValidationError):
        SessionEventPageRequest(session_id=uuid4(), after=after, limit=limit)


def test_sequenced_event_wraps_the_existing_typed_event() -> None:
    event = SessionStartedEvent(session_id=str(uuid4()))
    item = SequencedSessionEvent(sequence=4, event=event)
    page = SessionEventPage(items=(item,), next_after=4)

    assert page.items[0].sequence == 4
    assert page.items[0].event is event
    assert "sequence" not in event.model_dump()
