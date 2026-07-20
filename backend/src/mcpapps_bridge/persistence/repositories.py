"""SQLAlchemy repository adapters for managed domain records."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import AnyHttpUrl, TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mcpapps_bridge.domain import (
    BridgeSessionRecord,
    BridgeSessionStatus,
    EndpointBinding,
    EndpointDefinition,
    EndpointMode,
    EndpointSessionPolicy,
    SseConnection,
    StdioConnection,
    StreamableHttpConnection,
    UpstreamServerDefinition,
    UpstreamSessionMode,
)

from .models import (
    BridgeSessionRow,
    EndpointBindingRevisionRow,
    EndpointBindingRow,
    EndpointRevisionRow,
    EndpointRow,
    UpstreamRevisionRow,
    UpstreamServerRow,
)

HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


class SqlAlchemyUpstreamServerRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, server: UpstreamServerDefinition) -> None:
        try:
            async with self._session_factory.begin() as session:
                head = _upstream_to_row(server)
                session.add(head)
                await session.flush()
                revision_id = uuid4()
                session.add(_upstream_revision_to_row(server, revision_id))
                await session.flush()
                head.current_revision_id = revision_id
        except IntegrityError as exc:
            raise ValueError(f"Upstream server already exists: {server.server_id}") from exc

    async def get(self, server_id: UUID) -> UpstreamServerDefinition | None:
        async with self._session_factory() as session:
            row = await session.get(UpstreamServerRow, server_id)
            return _upstream_from_row(row) if row is not None else None

    async def list(self) -> list[UpstreamServerDefinition]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(select(UpstreamServerRow).order_by(UpstreamServerRow.slug))
            ).all()
            return [_upstream_from_row(row) for row in rows]


class SqlAlchemyEndpointRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, endpoint: EndpointDefinition) -> None:
        try:
            async with self._session_factory.begin() as session:
                head = _endpoint_to_row(endpoint)
                session.add(head)
                await session.flush()
                revision_id = uuid4()
                session.add(_endpoint_revision_to_row(endpoint, revision_id))
                await session.flush()
                session.add_all(
                    _binding_to_row(endpoint.endpoint_id, item) for item in endpoint.bindings
                )
                for binding in endpoint.bindings:
                    upstream_revision_id = await session.scalar(
                        select(UpstreamServerRow.current_revision_id).where(
                            UpstreamServerRow.server_id == binding.upstream_server_id
                        )
                    )
                    if upstream_revision_id is None:
                        raise ValueError(
                            f"Unknown or unpublished upstream server: {binding.upstream_server_id}"
                        )
                    session.add(
                        EndpointBindingRevisionRow(
                            binding_revision_id=uuid4(),
                            binding_id=binding.binding_id,
                            endpoint_revision_id=revision_id,
                            upstream_revision_id=upstream_revision_id,
                            namespace=binding.namespace,
                            priority=binding.priority,
                            enabled=binding.enabled,
                        )
                    )
                head.current_revision_id = revision_id
        except IntegrityError as exc:
            raise ValueError(f"Endpoint already exists: {endpoint.endpoint_id}") from exc

    async def get(self, endpoint_id: UUID) -> EndpointDefinition | None:
        async with self._session_factory() as session:
            row = await session.get(EndpointRow, endpoint_id)
            if row is None:
                return None
            return await _endpoint_from_row(session, row)

    async def get_by_slug(self, slug: str) -> EndpointDefinition | None:
        async with self._session_factory() as session:
            row = await session.scalar(select(EndpointRow).where(EndpointRow.slug == slug))
            if row is None:
                return None
            return await _endpoint_from_row(session, row)

    async def list(self) -> list[EndpointDefinition]:
        async with self._session_factory() as session:
            rows = (await session.scalars(select(EndpointRow).order_by(EndpointRow.slug))).all()
            return [await _endpoint_from_row(session, row) for row in rows]


class SqlAlchemyBridgeSessionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, session: BridgeSessionRecord) -> None:
        try:
            async with self._session_factory.begin() as db_session:
                db_session.add(_bridge_session_to_row(session))
        except IntegrityError as exc:
            raise ValueError(f"Bridge session already exists: {session.session_id}") from exc

    async def update(self, session: BridgeSessionRecord) -> None:
        try:
            async with self._session_factory.begin() as db_session:
                row = await db_session.get(BridgeSessionRow, session.session_id)
                if row is None:
                    raise KeyError(f"Unknown bridge session: {session.session_id}")
                _update_bridge_session_row(row, session)
        except IntegrityError as exc:
            transport_id = session.downstream_transport_session_id
            raise ValueError(f"Transport session already bound: {transport_id}") from exc

    async def get(self, session_id: UUID) -> BridgeSessionRecord | None:
        async with self._session_factory() as session:
            row = await session.get(BridgeSessionRow, session_id)
            return _bridge_session_from_row(row) if row is not None else None

    async def get_by_transport_session_id(
        self,
        transport_session_id: str,
    ) -> BridgeSessionRecord | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(BridgeSessionRow).where(
                    BridgeSessionRow.downstream_transport_session_id == transport_session_id
                )
            )
            return _bridge_session_from_row(row) if row is not None else None

    async def list(self, endpoint_id: UUID | None = None) -> list[BridgeSessionRecord]:
        statement = select(BridgeSessionRow).order_by(BridgeSessionRow.created_at.desc())
        if endpoint_id is not None:
            statement = statement.where(BridgeSessionRow.endpoint_id == endpoint_id)
        async with self._session_factory() as session:
            rows = (await session.scalars(statement)).all()
            return [_bridge_session_from_row(row) for row in rows]


async def seed_topology_if_empty(
    session_factory: async_sessionmaker[AsyncSession],
    upstream_servers: list[UpstreamServerDefinition],
    endpoints: list[EndpointDefinition],
) -> bool:
    """Atomically seed topology only when both topology tables are empty."""
    async with session_factory.begin() as session:
        existing_upstream = await session.scalar(select(UpstreamServerRow.server_id).limit(1))
        existing_endpoint = await session.scalar(select(EndpointRow.endpoint_id).limit(1))
        if existing_upstream is not None or existing_endpoint is not None:
            return False
        upstream_rows = {server.server_id: _upstream_to_row(server) for server in upstream_servers}
        session.add_all(upstream_rows.values())
        await session.flush()
        upstream_revision_ids: dict[UUID, UUID] = {}
        for server in upstream_servers:
            revision_id = uuid4()
            upstream_revision_ids[server.server_id] = revision_id
            session.add(_upstream_revision_to_row(server, revision_id))
        await session.flush()
        for server_id, revision_id in upstream_revision_ids.items():
            upstream_rows[server_id].current_revision_id = revision_id

        endpoint_rows = {endpoint.endpoint_id: _endpoint_to_row(endpoint) for endpoint in endpoints}
        for endpoint in endpoints:
            session.add(endpoint_rows[endpoint.endpoint_id])
        await session.flush()
        endpoint_revision_ids: dict[UUID, UUID] = {}
        for endpoint in endpoints:
            revision_id = uuid4()
            endpoint_revision_ids[endpoint.endpoint_id] = revision_id
            session.add(_endpoint_revision_to_row(endpoint, revision_id))
        await session.flush()
        for endpoint in endpoints:
            session.add_all(
                _binding_to_row(endpoint.endpoint_id, item) for item in endpoint.bindings
            )
            session.add_all(
                EndpointBindingRevisionRow(
                    binding_revision_id=uuid4(),
                    binding_id=item.binding_id,
                    endpoint_revision_id=endpoint_revision_ids[endpoint.endpoint_id],
                    upstream_revision_id=upstream_revision_ids[item.upstream_server_id],
                    namespace=item.namespace,
                    priority=item.priority,
                    enabled=item.enabled,
                )
                for item in endpoint.bindings
            )
            endpoint_rows[endpoint.endpoint_id].current_revision_id = endpoint_revision_ids[
                endpoint.endpoint_id
            ]
        return True


async def mark_interrupted_sessions_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    now = datetime.now(timezone.utc)
    async with session_factory.begin() as session:
        interrupted_ids = list(
            await session.scalars(
                select(BridgeSessionRow.session_id).where(
                    BridgeSessionRow.status.in_(["starting", "active", "closing"])
                )
            )
        )
        if not interrupted_ids:
            return 0
        await session.execute(
            update(BridgeSessionRow)
            .where(BridgeSessionRow.session_id.in_(interrupted_ids))
            .values(
                status="failed",
                last_activity_at=now,
                closed_at=now,
                error_message="Gateway process restarted before the session closed",
            )
        )
        return len(interrupted_ids)


def _upstream_to_row(server: UpstreamServerDefinition) -> UpstreamServerRow:
    connection = server.connection
    row = UpstreamServerRow(
        server_id=server.server_id,
        slug=server.slug,
        display_name=server.display_name,
        transport=connection.transport,
        enabled=server.enabled,
        metadata_json=server.metadata,
    )
    if isinstance(connection, StreamableHttpConnection):
        row.url = str(connection.url)
        row.headers_json = connection.headers
        row.timeout_seconds = connection.timeout_seconds
    elif isinstance(connection, SseConnection):
        row.url = str(connection.url)
        row.headers_json = connection.headers
    else:
        row.command = connection.command
        row.args_json = connection.args
        row.cwd = str(connection.cwd) if connection.cwd is not None else None
        row.env_json = connection.env
    return row


def _upstream_revision_to_row(
    server: UpstreamServerDefinition,
    revision_id: UUID,
) -> UpstreamRevisionRow:
    head = _upstream_to_row(server)
    return UpstreamRevisionRow(
        revision_id=revision_id,
        server_id=server.server_id,
        revision_number=1,
        slug=head.slug,
        display_name=head.display_name,
        transport=head.transport,
        url=head.url,
        command=head.command,
        args_json=head.args_json,
        cwd=head.cwd,
        env_json=head.env_json,
        headers_json=head.headers_json,
        timeout_seconds=head.timeout_seconds,
        enabled=head.enabled,
        metadata_json=head.metadata_json,
        created_at=datetime.now(timezone.utc),
    )


def _upstream_from_row(row: UpstreamServerRow) -> UpstreamServerDefinition:
    if row.transport == "streamable-http":
        connection = StreamableHttpConnection(
            url=HTTP_URL_ADAPTER.validate_python(row.url),
            headers=row.headers_json,
            timeout_seconds=row.timeout_seconds or 30.0,
        )
    elif row.transport == "sse":
        connection = SseConnection(
            url=HTTP_URL_ADAPTER.validate_python(row.url),
            headers=row.headers_json,
        )
    elif row.transport == "stdio":
        if row.command is None:
            raise ValueError(f"Persisted stdio upstream has no command: {row.server_id}")
        connection = StdioConnection(
            command=row.command,
            args=row.args_json,
            cwd=Path(row.cwd) if row.cwd is not None else None,
            env=row.env_json,
        )
    else:
        raise ValueError(f"Unsupported persisted upstream transport: {row.transport}")
    return UpstreamServerDefinition(
        server_id=row.server_id,
        slug=row.slug,
        display_name=row.display_name,
        connection=connection,
        enabled=row.enabled,
        metadata=row.metadata_json,
    )


def _endpoint_to_row(endpoint: EndpointDefinition) -> EndpointRow:
    return EndpointRow(
        endpoint_id=endpoint.endpoint_id,
        slug=endpoint.slug,
        display_name=endpoint.display_name,
        mode=endpoint.mode.value,
        upstream_session_mode=endpoint.session_policy.upstream_session_mode.value,
        lazy_upstream_connections=endpoint.session_policy.lazy_upstream_connections,
        idle_timeout_seconds=endpoint.session_policy.idle_timeout_seconds,
        enabled=endpoint.enabled,
        metadata_json=endpoint.metadata,
    )


def _endpoint_revision_to_row(
    endpoint: EndpointDefinition,
    revision_id: UUID,
) -> EndpointRevisionRow:
    return EndpointRevisionRow(
        revision_id=revision_id,
        endpoint_id=endpoint.endpoint_id,
        revision_number=1,
        slug=endpoint.slug,
        display_name=endpoint.display_name,
        mode=endpoint.mode.value,
        upstream_session_mode=endpoint.session_policy.upstream_session_mode.value,
        lazy_upstream_connections=endpoint.session_policy.lazy_upstream_connections,
        idle_timeout_seconds=endpoint.session_policy.idle_timeout_seconds,
        enabled=endpoint.enabled,
        metadata_json=endpoint.metadata,
        created_at=datetime.now(timezone.utc),
    )


def _binding_to_row(endpoint_id: UUID, binding: EndpointBinding) -> EndpointBindingRow:
    return EndpointBindingRow(
        binding_id=binding.binding_id,
        endpoint_id=endpoint_id,
        upstream_server_id=binding.upstream_server_id,
        namespace=binding.namespace,
        priority=binding.priority,
        enabled=binding.enabled,
    )


async def _endpoint_from_row(
    session: AsyncSession,
    row: EndpointRow,
) -> EndpointDefinition:
    bindings = (
        await session.scalars(
            select(EndpointBindingRow)
            .where(EndpointBindingRow.endpoint_id == row.endpoint_id)
            .order_by(EndpointBindingRow.priority, EndpointBindingRow.binding_id)
        )
    ).all()
    return EndpointDefinition(
        endpoint_id=row.endpoint_id,
        slug=row.slug,
        display_name=row.display_name,
        mode=EndpointMode(row.mode),
        bindings=[
            EndpointBinding(
                binding_id=binding.binding_id,
                upstream_server_id=binding.upstream_server_id,
                namespace=binding.namespace,
                priority=binding.priority,
                enabled=binding.enabled,
            )
            for binding in bindings
        ],
        session_policy=EndpointSessionPolicy(
            upstream_session_mode=UpstreamSessionMode(row.upstream_session_mode),
            lazy_upstream_connections=row.lazy_upstream_connections,
            idle_timeout_seconds=row.idle_timeout_seconds,
        ),
        enabled=row.enabled,
        metadata=row.metadata_json,
    )


def _bridge_session_to_row(bridge_session: BridgeSessionRecord) -> BridgeSessionRow:
    row = BridgeSessionRow(
        session_id=bridge_session.session_id,
        endpoint_id=bridge_session.endpoint_id,
        endpoint_revision_id=bridge_session.endpoint_revision_id,
    )
    _update_bridge_session_row(row, bridge_session)
    return row


def _update_bridge_session_row(
    row: BridgeSessionRow,
    bridge_session: BridgeSessionRecord,
) -> None:
    row.endpoint_id = bridge_session.endpoint_id
    row.endpoint_revision_id = bridge_session.endpoint_revision_id
    row.downstream_transport_session_id = bridge_session.downstream_transport_session_id
    row.status = bridge_session.status.value
    row.created_at = bridge_session.created_at
    row.last_activity_at = bridge_session.last_activity_at
    row.closed_at = bridge_session.closed_at
    row.error_message = bridge_session.error_message


def _bridge_session_from_row(row: BridgeSessionRow) -> BridgeSessionRecord:
    return BridgeSessionRecord(
        session_id=row.session_id,
        endpoint_id=row.endpoint_id,
        endpoint_revision_id=row.endpoint_revision_id,
        downstream_transport_session_id=row.downstream_transport_session_id,
        status=BridgeSessionStatus(row.status),
        created_at=_as_utc(row.created_at),
        last_activity_at=_as_utc(row.last_activity_at),
        closed_at=_as_utc(row.closed_at) if row.closed_at is not None else None,
        error_message=row.error_message,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
