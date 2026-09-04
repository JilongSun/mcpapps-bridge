"""Explicit mappings between Gateway topology contracts and SQLite rows.

This is the only server module that understands both application topology values and relational
transport columns. Repository and revision-reader adapters share these mappings to prevent drift.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from mabrid.application.gateway.topology import (
    EndpointBinding,
    EndpointDefinition,
    SseConnection,
    StdioConnection,
    StreamableHttpConnection,
    UpstreamRevision,
    UpstreamServerDefinition,
)
from pydantic import AnyHttpUrl, TypeAdapter

from ..schema import (
    EndpointBindingRow,
    EndpointRevisionRow,
    EndpointRow,
    UpstreamRevisionRow,
    UpstreamServerRow,
)

HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


def upstream_head_to_row(server: UpstreamServerDefinition) -> UpstreamServerRow:
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


def upstream_revision_to_row(
    server: UpstreamServerDefinition,
    revision_id: UUID,
) -> UpstreamRevisionRow:
    head = upstream_head_to_row(server)
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


def upstream_revision_from_row(row: UpstreamRevisionRow) -> UpstreamRevision:
    return UpstreamRevision(
        revision_id=row.revision_id,
        server_id=row.server_id,
        revision_number=row.revision_number,
        slug=row.slug,
        display_name=row.display_name,
        connection=_connection_from_row(row),
        enabled=row.enabled,
        metadata=row.metadata_json,
        created_at=as_utc(row.created_at),
    )


def endpoint_head_to_row(endpoint: EndpointDefinition) -> EndpointRow:
    return EndpointRow(
        endpoint_id=endpoint.endpoint_id,
        slug=endpoint.slug,
        display_name=endpoint.display_name,
        mode=endpoint.mode.value,
        enabled=endpoint.enabled,
        metadata_json=endpoint.metadata,
    )


def endpoint_revision_to_row(
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
        enabled=endpoint.enabled,
        metadata_json=endpoint.metadata,
        created_at=datetime.now(timezone.utc),
    )


def binding_to_row(endpoint_id: UUID, binding: EndpointBinding) -> EndpointBindingRow:
    return EndpointBindingRow(
        binding_id=binding.binding_id,
        endpoint_id=endpoint_id,
        upstream_server_id=binding.upstream_server_id,
        namespace=binding.namespace,
        priority=binding.priority,
        enabled=binding.enabled,
    )


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _connection_from_row(
    row: UpstreamServerRow | UpstreamRevisionRow,
) -> StreamableHttpConnection | SseConnection | StdioConnection:
    if row.transport == "streamable-http":
        return StreamableHttpConnection(
            url=HTTP_URL_ADAPTER.validate_python(row.url),
            headers=row.headers_json,
            timeout_seconds=row.timeout_seconds or 30.0,
        )
    if row.transport == "sse":
        return SseConnection(
            url=HTTP_URL_ADAPTER.validate_python(row.url),
            headers=row.headers_json,
        )
    if row.transport == "stdio":
        if row.command is None:
            raise ValueError(f"Persisted stdio upstream has no command: {row.server_id}")
        return StdioConnection(
            command=row.command,
            args=row.args_json,
            cwd=Path(row.cwd) if row.cwd is not None else None,
            env=row.env_json,
        )
    raise ValueError(f"Unsupported persisted upstream transport: {row.transport}")
