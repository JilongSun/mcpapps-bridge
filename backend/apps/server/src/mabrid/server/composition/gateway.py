"""Compose the managed Gateway application with SQLite and bridge-core adapters.

This module is the single boundary that converts resolved deployment topology into application
seed contracts and injects infrastructure ports. Runtime behavior remains in lower packages.
"""

from __future__ import annotations

import re

from mabrid.bridge import EndpointMode
from mabrid.application.gateway.sessions import GatewaySessionCoordinator
from mabrid.application.gateway.topology import (
    EndpointBinding,
    EndpointDefinition,
    SseConnection,
    StdioConnection,
    StreamableHttpConnection,
    UpstreamConnection,
    UpstreamServerDefinition,
)
from pydantic import AnyHttpUrl, TypeAdapter

from mabrid.server.config import RuntimeConfiguration, RuntimeUpstreamConfig
from mabrid.server.logging import get_logger
from mabrid.server.persistence import SqliteDatabase
from mabrid.server.persistence.sessions import (
    SqlAlchemyBridgeSessionRepository,
    SqlAlchemyBridgeSessionStoreFactory,
    mark_interrupted_sessions_failed,
)
from mabrid.server.persistence.topology import (
    SqlAlchemyTopologyReader,
    seed_topology_if_empty,
)

logger = get_logger(__name__)
HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


async def compose_gateway(
    configuration: RuntimeConfiguration,
    database: SqliteDatabase,
) -> GatewaySessionCoordinator:
    upstreams, endpoints = _build_topology_seed(configuration)
    logger.info(
        "Composing Gateway: %d upstream(s), %d endpoint(s)",
        len(upstreams),
        len(endpoints),
    )
    await seed_topology_if_empty(database.session_factory, upstreams, endpoints)
    await mark_interrupted_sessions_failed(database.session_factory)
    coordinator = GatewaySessionCoordinator(
        SqlAlchemyTopologyReader(database.session_factory),
        SqlAlchemyBridgeSessionRepository(database.session_factory),
        SqlAlchemyBridgeSessionStoreFactory(database.session_factory),
    )
    await coordinator.load_published_endpoints()
    return coordinator


def _build_topology_seed(
    configuration: RuntimeConfiguration,
) -> tuple[list[UpstreamServerDefinition], list[EndpointDefinition]]:
    upstreams: dict[str, UpstreamServerDefinition] = {}
    for name, upstream in configuration.upstreams.items():
        definition = UpstreamServerDefinition(
            slug=_normalize_slug(name),
            display_name=name,
            connection=_to_application_connection(upstream),
        )
        upstreams[name] = definition
        logger.info(
            "Upstream server: name=%s slug=%s transport=%s",
            name,
            definition.slug,
            upstream.transport,
        )

    if configuration.diagnostic_upstream is not None:
        selected = upstreams[configuration.diagnostic_upstream]
        return list(upstreams.values()), [
            EndpointDefinition(
                slug=selected.slug,
                display_name=configuration.bridge.proxy_name or selected.display_name,
                bindings=[EndpointBinding(upstream_server_id=selected.server_id)],
            )
        ]

    endpoints = [
        EndpointDefinition(
            slug=_normalize_slug(name),
            display_name=endpoint.display_name or name,
            mode=EndpointMode(endpoint.mode),
            bindings=[
                EndpointBinding(
                    upstream_server_id=upstreams[binding.upstream].server_id,
                    namespace=binding.namespace,
                    priority=binding.priority,
                    enabled=binding.enabled,
                )
                for binding in endpoint.bindings
            ],
            enabled=endpoint.enabled,
        )
        for name, endpoint in configuration.endpoints.items()
    ]
    for endpoint in endpoints:
        logger.info(
            "Published topology seed: slug=%s mode=%s bindings=%d enabled=%s",
            endpoint.slug,
            endpoint.mode.value,
            len(endpoint.bindings),
            endpoint.enabled,
        )
    return list(upstreams.values()), endpoints


def _to_application_connection(upstream: RuntimeUpstreamConfig) -> UpstreamConnection:
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


def _normalize_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    if not slug or not slug[0].isalpha():
        return f"server-{slug}" if slug else "server"
    return slug
