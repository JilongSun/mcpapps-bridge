"""Application assembly for a managed bridge runtime."""

from __future__ import annotations

import re

from pydantic import AnyHttpUrl, TypeAdapter

from mcpapps_bridge.domain import (
    EndpointBinding,
    EndpointDefinition,
    SseConnection,
    StdioConnection,
    StreamableHttpConnection,
    UpstreamConnection,
    UpstreamServerDefinition,
)
from mcpapps_bridge.repositories import (
    BridgeSessionRepository,
    EndpointRepository,
    InMemoryBridgeSessionRepository,
    InMemoryEndpointRepository,
    InMemoryUpstreamServerRepository,
    UpstreamServerRepository,
)
from mcpapps_bridge.session import BridgeSessionStoreFactory, InMemoryBridgeSessionStoreFactory

from .manager import BridgeManager
from .upstream import UpstreamMcpClientFactory, UpstreamServerConfig

HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


async def build_bridge_manager(
    upstream_config: UpstreamServerConfig,
    *,
    upstream_name: str,
    display_name: str | None = None,
    version: str = "0.1.0",
    upstream_client_factory: UpstreamMcpClientFactory | None = None,
) -> BridgeManager:
    slug = _normalize_slug(upstream_name)
    server = UpstreamServerDefinition(
        slug=slug,
        display_name=display_name or upstream_name,
        connection=to_domain_connection(upstream_config),
    )
    endpoint = EndpointDefinition(
        slug=slug,
        display_name=display_name or upstream_name,
        bindings=[EndpointBinding(upstream_server_id=server.server_id)],
    )
    manager = BridgeManager(
        InMemoryUpstreamServerRepository(),
        InMemoryEndpointRepository(),
        InMemoryBridgeSessionRepository(),
        InMemoryBridgeSessionStoreFactory(),
        upstream_client_factory=upstream_client_factory,
        version=version,
    )
    await manager.add_upstream_server(server)
    await manager.add_endpoint(endpoint)
    return manager


async def assemble_bridge_manager(
    upstream_servers: UpstreamServerRepository,
    endpoints: EndpointRepository,
    sessions: BridgeSessionRepository,
    session_store_factory: BridgeSessionStoreFactory,
    *,
    version: str = "0.1.0",
    upstream_client_factory: UpstreamMcpClientFactory | None = None,
) -> BridgeManager:
    manager = BridgeManager(
        upstream_servers,
        endpoints,
        sessions,
        session_store_factory,
        upstream_client_factory=upstream_client_factory,
        version=version,
    )
    await manager.load_published_endpoints()
    return manager


def _normalize_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    if not slug or not slug[0].isalpha():
        slug = f"server-{slug}" if slug else "server"
    return slug


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
