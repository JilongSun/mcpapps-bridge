"""Secret-safe mappings from persisted topology heads to management read models."""

from __future__ import annotations

from pathlib import Path

from mabrid.application.gateway.topology import (
    ConfiguredKey,
    ManagedSseConnection,
    ManagedStdioConnection,
    ManagedStreamableHttpConnection,
    ManagedUpstreamConnection,
)
from pydantic import AnyHttpUrl, TypeAdapter

from ..schema import UpstreamServerRow

HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


def managed_connection_from_row(row: UpstreamServerRow) -> ManagedUpstreamConnection:
    if row.transport == "streamable-http":
        return ManagedStreamableHttpConnection(
            url=HTTP_URL_ADAPTER.validate_python(row.url),
            headers=_configured_keys(row.headers_json),
            timeout_seconds=row.timeout_seconds or 30.0,
        )
    if row.transport == "sse":
        return ManagedSseConnection(
            url=HTTP_URL_ADAPTER.validate_python(row.url),
            headers=_configured_keys(row.headers_json),
        )
    if row.transport == "stdio":
        if row.command is None:
            raise ValueError(f"Persisted stdio upstream has no command: {row.server_id}")
        return ManagedStdioConnection(
            command=row.command,
            args=tuple(row.args_json),
            cwd=Path(row.cwd) if row.cwd is not None else None,
            env=_configured_keys(row.env_json),
        )
    raise ValueError(f"Unsupported persisted upstream transport: {row.transport}")


def _configured_keys(values: dict[str, str]) -> tuple[ConfiguredKey, ...]:
    return tuple(ConfiguredKey(name=name) for name in sorted(values))
