"""Top-level resource assembly for one deployable Mabrid server process.

Bootstrap owns migration and composition failure cleanup. Long-running Gateway and HTTP lifecycles
start later in the server runtime and close in reverse ownership order.
"""

from __future__ import annotations

from dataclasses import dataclass

from mabrid.application.gateway.sessions import (
    BridgeSessionObserverFactory,
    CompositeBridgeSessionObserverFactory,
    GatewaySessionCoordinator,
)

from mabrid.server.config import RuntimeConfiguration
from mabrid.server.logging import get_logger
from mabrid.server.persistence import SqliteDatabase

from .agent_host import AgentHostComposition, compose_agent_host
from .gateway import GatewayManagementComposition, compose_gateway
from .mcp_apps import McpAppsComposition, compose_mcp_apps

logger = get_logger(__name__)


@dataclass(frozen=True)
class BootstrapResult:
    gateway: GatewaySessionCoordinator
    gateway_management: GatewayManagementComposition
    database: SqliteDatabase
    agent_host: AgentHostComposition | None
    mcp_apps: McpAppsComposition | None


async def bootstrap_server(configuration: RuntimeConfiguration) -> BootstrapResult:
    database = SqliteDatabase(configuration.storage.sqlite_path)
    logger.info("SQLite database opened: %s", configuration.storage.sqlite_path)
    agent_host: AgentHostComposition | None = None
    mcp_apps: McpAppsComposition | None = None
    try:
        if configuration.storage.auto_migrate:
            logger.info("Running database migrations")
            await database.migrate()
        gateway = await compose_gateway(configuration, database)
        agent_host = await compose_agent_host(configuration, gateway.runtime)
        if agent_host is not None:
            observer_factories: list[BridgeSessionObserverFactory] = [
                agent_host.bridge_observer_factory
            ]
            if configuration.agent_host.mcp_apps_enabled:
                mcp_apps = compose_mcp_apps(
                    agent_host.management.endpoint_slug,
                    agent_host.operation_attributions,
                )
                observer_factories.append(mcp_apps.bridge_observer_factory)
            gateway.runtime.configure_session_observer_factory(
                CompositeBridgeSessionObserverFactory(observer_factories)
            )
    except BaseException:
        logger.exception("Bootstrap failed - closing composed resources")
        if agent_host is not None:
            await agent_host.runtime.close()
        await database.close()
        raise
    return BootstrapResult(
        gateway=gateway.runtime,
        gateway_management=gateway.management,
        database=database,
        agent_host=agent_host,
        mcp_apps=mcp_apps,
    )
