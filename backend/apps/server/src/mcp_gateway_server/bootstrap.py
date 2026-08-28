"""Application composition for configured SQLite storage."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from mcp_gateway_service import (
    AgentEndpointAssignment,
    AgentHostService,
    AgentTarget,
    EndpointBinding,
    EndpointDefinition,
    EndpointMode,
    GatewaySessionCoordinator,
    ManagedAgentRuntime,
    UpstreamServerDefinition,
)

from mcp_gateway_server.agent_runtime import build_agent_runtime
from mcp_gateway_server.config import RuntimeConfiguration
from mcp_gateway_server.logging import get_logger
from mcp_gateway_server.mcp import assemble_gateway_session_coordinator, to_domain_connection
from mcp_gateway_server.persistence import (
    SqlAlchemyBridgeSessionRepository,
    SqlAlchemyBridgeSessionStoreFactory,
    SqlAlchemyEndpointRepository,
    SqlAlchemyTopologyReader,
    SqlAlchemyUpstreamServerRepository,
    SqliteDatabase,
    mark_interrupted_sessions_failed,
    seed_topology_if_empty,
)

logger = get_logger(__name__)


class AsyncCloser(Protocol):
    async def close(self) -> None: ...


@dataclass(frozen=True)
class BootstrapResult:
    manager: GatewaySessionCoordinator
    storage: AsyncCloser
    agent_host: AgentHostComposition | None


@dataclass(frozen=True)
class AgentHostComposition:
    service: AgentHostService
    runtime: ManagedAgentRuntime


async def bootstrap_gateway(configuration: RuntimeConfiguration) -> BootstrapResult:
    upstreams, endpoints = _build_topology_seed(configuration)
    logger.info(
        "Bootstrapping gateway: %d upstream(s), %d endpoint(s)",
        len(upstreams),
        len(endpoints),
    )

    database = SqliteDatabase(configuration.storage.sqlite_path)
    logger.info("SQLite database opened: %s", configuration.storage.sqlite_path)
    agent_host: AgentHostComposition | None = None

    try:
        if configuration.storage.auto_migrate:
            logger.info("Running database migrations...")
            await database.migrate()
            logger.info("Database migrations complete")
        await seed_topology_if_empty(database.session_factory, upstreams, endpoints)
        await mark_interrupted_sessions_failed(database.session_factory)
        upstream_repository = SqlAlchemyUpstreamServerRepository(database.session_factory)
        endpoint_repository = SqlAlchemyEndpointRepository(database.session_factory)
        manager = await assemble_gateway_session_coordinator(
            upstream_repository,
            endpoint_repository,
            SqlAlchemyTopologyReader(database.session_factory),
            SqlAlchemyBridgeSessionRepository(database.session_factory),
            SqlAlchemyBridgeSessionStoreFactory(database.session_factory),
        )
        logger.info("Bridge manager assembled successfully")
        agent_host = _assemble_agent_host(configuration, manager)
    except BaseException:
        logger.exception("Bootstrap failed — closing database")
        if agent_host is not None:
            await agent_host.runtime.close()
        await database.close()
        raise
    return BootstrapResult(manager=manager, storage=database, agent_host=agent_host)


def _assemble_agent_host(
    configuration: RuntimeConfiguration,
    manager: GatewaySessionCoordinator,
) -> AgentHostComposition | None:
    config = configuration.agent_host
    if not config.enabled:
        return None
    if config.target_id is None:
        raise ValueError("Enabled Agent Host configuration has no target ID")
    if config.endpoint_slug is None:
        raise ValueError("Enabled Agent Host configuration has no endpoint assignment")
    endpoint = manager.resolve_published_endpoint(config.endpoint_slug)
    if endpoint is None:
        raise ValueError(
            f"Agent Target '{config.target_id}' references endpoint "
            f"'{config.endpoint_slug}', which is not published and enabled"
        )
    runtime = build_agent_runtime(config.runtime)
    target = AgentTarget(
        target_id=config.target_id,
        runtime_profile=runtime.profile,
        endpoint_assignment=AgentEndpointAssignment(endpoint_slug=config.endpoint_slug),
    )
    logger.info(
        "Agent Target enabled: id=%s integration=%s endpoint=%s runtime_url=%s",
        target.target_id,
        target.runtime_profile.integration_kind,
        endpoint.path,
        config.runtime.base_url,
    )
    return AgentHostComposition(
        service=AgentHostService(target, runtime),
        runtime=runtime,
    )


def _build_topology_seed(
    configuration: RuntimeConfiguration,
) -> tuple[list[UpstreamServerDefinition], list[EndpointDefinition]]:
    upstreams: dict[str, UpstreamServerDefinition] = {}
    for name, upstream in configuration.upstreams.items():
        definition = UpstreamServerDefinition(
            slug=_normalize_slug(name),
            display_name=name,
            connection=to_domain_connection(upstream),
        )
        upstreams[name] = definition
        logger.info(
            "Upstream server: name=%s slug=%s transport=%s",
            name,
            definition.slug,
            upstream.transport,
        )
        if upstream.transport == "stdio":
            logger.debug("  stdio: command=%s args=%s", upstream.command, upstream.args)
        else:
            logger.debug("  http: url=%s", upstream.url)

    endpoint_configs = configuration.endpoints
    if configuration.diagnostic_upstream is not None:
        selected = upstreams[configuration.diagnostic_upstream]
        endpoints = [
            EndpointDefinition(
                slug=selected.slug,
                display_name=configuration.bridge.proxy_name or selected.display_name,
                bindings=[EndpointBinding(upstream_server_id=selected.server_id)],
            )
        ]
        return list(upstreams.values()), endpoints

    endpoints: list[EndpointDefinition] = []
    for name, endpoint in endpoint_configs.items():
        definition = EndpointDefinition(
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
        logger.info(
            "Endpoint: slug=%s display_name=%s mode=%s bindings=%d enabled=%s",
            definition.slug,
            definition.display_name,
            endpoint.mode,
            len(endpoint.bindings),
            endpoint.enabled,
        )
        for binding in endpoint.bindings:
            logger.debug(
                "  binding: upstream=%s namespace=%s priority=%d enabled=%s",
                binding.upstream,
                binding.namespace or "(default)",
                binding.priority,
                binding.enabled,
            )
        endpoints.append(definition)
    return list(upstreams.values()), endpoints


def _normalize_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    if not slug or not slug[0].isalpha():
        return f"server-{slug}" if slug else "server"
    return slug
