from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from mabrid.application.gateway.inspection import SessionEventPageRequest, SessionStatus
from mabrid.application.gateway.sessions import (
    BridgeSessionRecord,
    BridgeSessionStatus,
    SessionPageRequest,
)
from mabrid.application.gateway.topology import (
    EndpointBinding,
    EndpointDefinition,
    ManagedStdioConnection,
    ManagedStreamableHttpConnection,
    StdioConnection,
    StreamableHttpConnection,
    UpstreamServerDefinition,
)
from mabrid.bridge import EndpointMode
from pydantic import AnyHttpUrl, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mabrid.server.persistence import SqliteDatabase
from mabrid.server.persistence.schema import (
    EndpointBindingRow,
    EndpointRow,
    SessionEventRow,
    UpstreamServerRow,
)
from mabrid.server.persistence.sessions import (
    SqlAlchemyBridgeSessionRepository,
    SqlAlchemyBridgeSessionStoreFactory,
    SqlAlchemySessionHistoryReader,
    SqlAlchemySessionInspectionReader,
)
from mabrid.server.persistence.topology import (
    SqlAlchemyTopologySnapshotReader,
    seed_topology_if_empty,
)


async def _seed_topology(
    database: SqliteDatabase,
) -> tuple[UpstreamServerDefinition, UpstreamServerDefinition, EndpointDefinition]:
    stdio = UpstreamServerDefinition(
        slug="local-tools",
        display_name="Local Tools",
        connection=StdioConnection(
            command="fixture-server",
            args=["--stdio"],
            env={"GITHUB_TOKEN": "stdio-secret"},
        ),
    )
    http = UpstreamServerDefinition(
        slug="remote-tools",
        display_name="Remote Tools",
        connection=StreamableHttpConnection(
            url=AnyHttpUrl("https://upstream.example.test/mcp"),
            headers={"Authorization": "Bearer http-secret"},
            timeout_seconds=12,
        ),
        enabled=False,
    )
    aggregate = EndpointDefinition(
        slug="all-tools",
        display_name="All Tools",
        mode=EndpointMode.AGGREGATE,
        bindings=[
            EndpointBinding(upstream_server_id=stdio.server_id, namespace="local"),
            EndpointBinding(
                upstream_server_id=http.server_id,
                namespace="remote",
                priority=10,
                enabled=False,
            ),
        ],
    )
    disabled = EndpointDefinition(
        slug="remote-only",
        display_name="Remote Only",
        bindings=[EndpointBinding(upstream_server_id=http.server_id)],
        enabled=False,
    )
    await seed_topology_if_empty(
        database.session_factory,
        [stdio, http],
        [aggregate, disabled],
    )
    return stdio, http, aggregate


async def test_topology_snapshot_includes_disabled_heads_without_secret_values(
    tmp_path: Path,
) -> None:
    database = SqliteDatabase(tmp_path / "topology.db")
    try:
        await database.migrate()
        stdio, http, aggregate = await _seed_topology(database)

        snapshot = await SqlAlchemyTopologySnapshotReader(database.session_factory).read_snapshot()
    finally:
        await database.close()

    assert [upstream.slug for upstream in snapshot.upstreams] == ["local-tools", "remote-tools"]
    assert [endpoint.slug for endpoint in snapshot.endpoints] == ["all-tools", "remote-only"]
    assert snapshot.upstreams[1].enabled is False
    assert snapshot.endpoints[1].enabled is False

    local_connection = snapshot.upstreams[0].connection
    remote_connection = snapshot.upstreams[1].connection
    assert isinstance(local_connection, ManagedStdioConnection)
    assert isinstance(remote_connection, ManagedStreamableHttpConnection)
    assert local_connection.env[0].name == "GITHUB_TOKEN"
    assert remote_connection.headers[0].name == "Authorization"
    serialized = snapshot.model_dump_json()
    assert "stdio-secret" not in serialized
    assert "http-secret" not in serialized

    managed_aggregate = snapshot.endpoints[0]
    assert managed_aggregate.endpoint_id == aggregate.endpoint_id
    binding_by_upstream = {
        binding.upstream_server_id: binding for binding in managed_aggregate.bindings
    }
    assert (
        binding_by_upstream[stdio.server_id].upstream_revision_id
        == snapshot.upstreams[0].current_revision.revision_id
    )
    assert (
        binding_by_upstream[http.server_id].upstream_revision_id
        == snapshot.upstreams[1].current_revision.revision_id
    )


CorruptTopology = Callable[[AsyncSession], Awaitable[None]]


async def _remove_upstream_head_revision(session: AsyncSession) -> None:
    row = await session.scalar(select(UpstreamServerRow).order_by(UpstreamServerRow.slug))
    assert row is not None
    row.current_revision_id = None


async def _point_upstream_head_to_another_owner(session: AsyncSession) -> None:
    rows = list((await session.scalars(select(UpstreamServerRow).order_by(UpstreamServerRow.slug))))
    assert len(rows) == 2
    rows[0].current_revision_id = rows[1].current_revision_id


async def _point_endpoint_head_to_another_owner(session: AsyncSession) -> None:
    rows = list((await session.scalars(select(EndpointRow).order_by(EndpointRow.slug))))
    assert len(rows) == 2
    rows[0].current_revision_id = rows[1].current_revision_id


async def _mismatch_binding_upstream_owner(session: AsyncSession) -> None:
    binding = await session.scalar(select(EndpointBindingRow).order_by(EndpointBindingRow.priority))
    assert binding is not None
    upstream = await session.scalar(
        select(UpstreamServerRow).where(UpstreamServerRow.server_id != binding.upstream_server_id)
    )
    assert upstream is not None
    binding.upstream_server_id = upstream.server_id


@pytest.mark.parametrize(
    ("corrupt", "message"),
    [
        (_remove_upstream_head_revision, "has no current revision"),
        (_point_upstream_head_to_another_owner, "belongs to another upstream"),
        (_point_endpoint_head_to_another_owner, "belongs to another endpoint"),
        (_mismatch_binding_upstream_owner, "binding references another upstream"),
    ],
)
async def test_topology_snapshot_rejects_incoherent_persistence(
    tmp_path: Path,
    corrupt: CorruptTopology,
    message: str,
) -> None:
    database = SqliteDatabase(tmp_path / "corrupt.db")
    try:
        await database.migrate()
        await _seed_topology(database)
        async with database.session_factory.begin() as session:
            await corrupt(session)

        with pytest.raises(ValueError, match=message):
            await SqlAlchemyTopologySnapshotReader(database.session_factory).read_snapshot()
    finally:
        await database.close()


async def test_session_history_uses_stable_keyset_pagination_and_filters(tmp_path: Path) -> None:
    database = SqliteDatabase(tmp_path / "sessions.db")
    try:
        await database.migrate()
        _, _, endpoint = await _seed_topology(database)
        topology = await SqlAlchemyTopologySnapshotReader(database.session_factory).read_snapshot()
        revision_id = topology.endpoints[0].current_revision.revision_id
        repository = SqlAlchemyBridgeSessionRepository(database.session_factory)
        created_at = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)
        records = [
            BridgeSessionRecord(
                session_id=UUID(int=value),
                endpoint_id=endpoint.endpoint_id,
                endpoint_revision_id=revision_id,
                status=BridgeSessionStatus.ACTIVE if value != 1 else BridgeSessionStatus.CLOSED,
                created_at=created_at if value != 1 else created_at - timedelta(minutes=1),
                last_activity_at=created_at,
            )
            for value in (1, 3, 2)
        ]
        for record in records:
            await repository.add(record)

        reader = SqlAlchemySessionHistoryReader(database.session_factory)
        first = await reader.list_sessions(SessionPageRequest(limit=2))
        assert [item.session_id.int for item in first.items] == [3, 2]
        assert first.next_keyset is not None
        second = await reader.list_sessions(SessionPageRequest(limit=2, before=first.next_keyset))
        assert [item.session_id.int for item in second.items] == [1]
        assert second.next_keyset is None

        active = await reader.list_sessions(
            SessionPageRequest(
                endpoint_id=endpoint.endpoint_id,
                status=BridgeSessionStatus.ACTIVE,
            )
        )
        assert [item.session_id.int for item in active.items] == [3, 2]
        assert await reader.get_session(UUID(int=999)) is None
    finally:
        await database.close()


async def test_inspection_reader_pages_events_and_defaults_missing_snapshot(
    tmp_path: Path,
) -> None:
    database = SqliteDatabase(tmp_path / "inspection.db")
    try:
        await database.migrate()
        _, _, endpoint = await _seed_topology(database)
        topology = await SqlAlchemyTopologySnapshotReader(database.session_factory).read_snapshot()
        record = BridgeSessionRecord(
            endpoint_id=endpoint.endpoint_id,
            endpoint_revision_id=topology.endpoints[0].current_revision.revision_id,
        )
        await SqlAlchemyBridgeSessionRepository(database.session_factory).add(record)
        reader = SqlAlchemySessionInspectionReader(database.session_factory)

        default_snapshot = await reader.get_snapshot(record.session_id)
        assert default_snapshot is not None
        assert default_snapshot.status is SessionStatus.STARTING
        assert await reader.get_snapshot(UUID(int=999)) is None
        assert await reader.list_events(SessionEventPageRequest(session_id=UUID(int=999))) is None

        store = await SqlAlchemyBridgeSessionStoreFactory(database.session_factory).get(
            record.session_id
        )
        assert store is not None
        await store.start()
        await store.record_error("fixture failure", {"kind": "fixture"})

        first = await reader.list_events(
            SessionEventPageRequest(session_id=record.session_id, limit=1)
        )
        assert first is not None
        assert [item.sequence for item in first.items] == [1]
        assert first.next_after == 1
        second = await reader.list_events(
            SessionEventPageRequest(session_id=record.session_id, after=1, limit=1)
        )
        assert second is not None
        assert [item.sequence for item in second.items] == [2]
        assert second.next_after is None
    finally:
        await database.close()


async def test_inspection_reader_rejects_an_invalid_persisted_event(tmp_path: Path) -> None:
    database = SqliteDatabase(tmp_path / "invalid-event.db")
    try:
        await database.migrate()
        _, _, endpoint = await _seed_topology(database)
        topology = await SqlAlchemyTopologySnapshotReader(database.session_factory).read_snapshot()
        record = BridgeSessionRecord(
            endpoint_id=endpoint.endpoint_id,
            endpoint_revision_id=topology.endpoints[0].current_revision.revision_id,
        )
        await SqlAlchemyBridgeSessionRepository(database.session_factory).add(record)
        async with database.session_factory.begin() as session:
            session.add(
                SessionEventRow(
                    event_id=UUID(int=50),
                    session_id=record.session_id,
                    sequence=1,
                    kind="invalid",
                    payload_json={"kind": "invalid"},
                    created_at=datetime.now(timezone.utc),
                )
            )

        with pytest.raises(ValidationError):
            await SqlAlchemySessionInspectionReader(database.session_factory).list_events(
                SessionEventPageRequest(session_id=record.session_id)
            )
    finally:
        await database.close()
