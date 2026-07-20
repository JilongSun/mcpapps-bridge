"""Application assembly for a managed bridge runtime."""

from __future__ import annotations

from pydantic import AnyHttpUrl, TypeAdapter

from mcpapps_bridge.domain import (
    SseConnection,
    StdioConnection,
    StreamableHttpConnection,
    UpstreamConnection,
)
from mcpapps_bridge.repositories import (
    BridgeSessionRepository,
    EndpointRepository,
    TopologyReader,
    UpstreamServerRepository,
)
from mcpapps_bridge.session import BridgeSessionStoreFactory

from .manager import BridgeManager
from .upstream import UpstreamMcpClientFactory, UpstreamServerConfig

HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


async def assemble_bridge_manager(
    upstream_servers: UpstreamServerRepository,
    endpoints: EndpointRepository,
    topology: TopologyReader,
    sessions: BridgeSessionRepository,
    session_store_factory: BridgeSessionStoreFactory,
    *,
    version: str = "0.1.0",
    upstream_client_factory: UpstreamMcpClientFactory | None = None,
) -> BridgeManager:
    manager = BridgeManager(
        upstream_servers,
        endpoints,
        topology,
        sessions,
        session_store_factory,
        upstream_client_factory=upstream_client_factory,
        version=version,
    )
    await manager.load_published_endpoints()
    return manager


def to_domain_connection(upstream: UpstreamServerConfig) -> UpstreamConnection:
    if upstream.transport == "streamable-http":
        if upstream.url is None:
            raise ValueError("streamable-http upstream requires a URL")
        return StreamableHttpConnection(
            url=HTTP_URL_ADAPTER.validate_python(upstream.url),
            headers=upstream.headers,
            timeout_seconds=upstream.httpx_timeout_seconds or 30.0,
        )
    if upstream.transport == "sse":
        if upstream.url is None:
            raise ValueError("SSE upstream requires a URL")
        return SseConnection(
            url=HTTP_URL_ADAPTER.validate_python(upstream.url),
            headers=upstream.headers,
        )
    if upstream.command is None:
        raise ValueError("stdio upstream requires a command")
    return StdioConnection(
        command=upstream.command,
        args=upstream.args,
        cwd=upstream.cwd,
        env=upstream.env,
    )
