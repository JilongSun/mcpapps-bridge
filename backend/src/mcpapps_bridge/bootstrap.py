"""Application composition for memory and SQLite storage profiles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from mcpapps_bridge.config import RuntimeConfiguration
from mcpapps_bridge.domain import (
    EndpointBinding,
    EndpointDefinition,
    EndpointMode,
    EndpointSessionPolicy,
    UpstreamServerDefinition,
    UpstreamSessionMode,
)
from mcpapps_bridge.mcp import BridgeManager, assemble_bridge_manager, to_domain_connection
from mcpapps_bridge.persistence import (
    SqlAlchemyBridgeSessionRepository,
    SqlAlchemyBridgeSessionStoreFactory,
    SqlAlchemyEndpointRepository,
    SqlAlchemyTopologyReader,
    SqlAlchemyUpstreamServerRepository,
    SqliteDatabase,
    mark_interrupted_sessions_failed,
    seed_topology_if_empty,
)
from mcpapps_bridge.repositories import (
    InMemoryBridgeSessionRepository,
    InMemoryEndpointRepository,
    InMemoryUpstreamServerRepository,
    RepositoryTopologyReader,
)
from mcpapps_bridge.session import InMemoryBridgeSessionStoreFactory


class AsyncCloser(Protocol):
    async def close(self) -> None: ...


@dataclass(frozen=True)
class BootstrapResult:
    manager: BridgeManager
    storage: AsyncCloser | None


async def bootstrap_gateway(configuration: RuntimeConfiguration) -> BootstrapResult:
    upstreams, endpoints = _build_topology_seed(configuration)
    if configuration.storage.profile == "memory":
        upstream_repository = InMemoryUpstreamServerRepository()
        endpoint_repository = InMemoryEndpointRepository()
        for upstream in upstreams:
            await upstream_repository.add(upstream)
        for endpoint in endpoints:
            await endpoint_repository.add(endpoint)
        manager = await assemble_bridge_manager(
            upstream_repository,
            endpoint_repository,
            RepositoryTopologyReader(upstream_repository, endpoint_repository),
            InMemoryBridgeSessionRepository(),
            InMemoryBridgeSessionStoreFactory(),
        )
        return BootstrapResult(manager=manager, storage=None)

    database = SqliteDatabase(configuration.storage.sqlite_path)
    try:
        if configuration.storage.auto_migrate:
            await database.migrate()
        await seed_topology_if_empty(database.session_factory, upstreams, endpoints)
        await mark_interrupted_sessions_failed(database.session_factory)
        upstream_repository = SqlAlchemyUpstreamServerRepository(database.session_factory)
        endpoint_repository = SqlAlchemyEndpointRepository(database.session_factory)
        manager = await assemble_bridge_manager(
            upstream_repository,
            endpoint_repository,
            SqlAlchemyTopologyReader(database.session_factory),
            SqlAlchemyBridgeSessionRepository(database.session_factory),
            SqlAlchemyBridgeSessionStoreFactory(database.session_factory),
        )
    except BaseException:
        await database.close()
        raise
    return BootstrapResult(manager=manager, storage=database)


def _build_topology_seed(
    configuration: RuntimeConfiguration,
) -> tuple[list[UpstreamServerDefinition], list[EndpointDefinition]]:
    upstreams = {
        name: UpstreamServerDefinition(
            slug=_normalize_slug(name),
            display_name=name,
            connection=to_domain_connection(upstream),
        )
        for name, upstream in configuration.upstreams.items()
    }
    endpoints: list[EndpointDefinition] = []
    for name, endpoint in configuration.endpoints.items():
        endpoints.append(
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
                session_policy=EndpointSessionPolicy(
                    upstream_session_mode=UpstreamSessionMode(endpoint.upstream_session_mode),
                    lazy_upstream_connections=endpoint.lazy_upstream_connections,
                    idle_timeout_seconds=endpoint.idle_timeout_seconds,
                ),
                enabled=endpoint.enabled,
            )
        )
    if not endpoints:
        default_name = configuration.default_upstream
        if default_name is None:
            if len(upstreams) != 1:
                raise ValueError(
                    "Legacy topology with multiple upstreams requires defaultUpstream or endpoints"
                )
            default_name = next(iter(upstreams))
        upstream = upstreams[default_name]
        endpoints.append(
            EndpointDefinition(
                slug=upstream.slug,
                display_name=configuration.bridge.proxy_name or upstream.display_name,
                bindings=[EndpointBinding(upstream_server_id=upstream.server_id)],
            )
        )
    return list(upstreams.values()), endpoints


def _normalize_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    if not slug or not slug[0].isalpha():
        return f"server-{slug}" if slug else "server"
    return slug
