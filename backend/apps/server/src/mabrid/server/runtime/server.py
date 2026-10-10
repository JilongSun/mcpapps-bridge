"""Uvicorn process runtime for the composed Mabrid HTTP application.

This outer shell owns listener configuration and process serving only. FastAPI composition and
application lifecycles remain delegated to the API and Gateway services.
"""

from __future__ import annotations

import uvicorn
from mabrid.application.agent_host import (
    AgentHostService,
    AgentSessionService,
    AgentHostCapabilityService,
)
from mabrid.application.gateway.sessions import GatewaySessionCoordinator
from mabrid.application.host import HostEventStream, HostSessionEventStream

from mabrid.server.api import create_app
from mabrid.server.composition import AgentHostManagementView, GatewayManagementComposition
from mabrid.server.logging import get_logger

logger = get_logger(__name__)


class MabridServerRuntime:
    def __init__(
        self,
        gateway: GatewaySessionCoordinator,
        *,
        agent_host: AgentHostService | None = None,
        host_events: HostEventStream | None = None,
        agent_sessions: AgentSessionService | None = None,
        host_session_events: HostSessionEventStream | None = None,
        agent_host_capabilities: AgentHostCapabilityService | None = None,
        gateway_management: GatewayManagementComposition | None = None,
        agent_host_management: AgentHostManagementView | None = None,
        api_host: str = "127.0.0.1",
        api_port: int = 8765,
    ) -> None:
        self._gateway = gateway
        self._agent_host = agent_host
        self._host_events = host_events
        self._agent_sessions = agent_sessions
        self._host_session_events = host_session_events
        self._agent_host_capabilities = agent_host_capabilities
        self._gateway_management = gateway_management
        self._agent_host_management = agent_host_management
        self._api_host = api_host
        self._api_port = api_port

    async def serve(self) -> None:
        app = create_app(
            self._gateway,
            agent_host=self._agent_host,
            host_events=self._host_events,
            agent_sessions=self._agent_sessions,
            host_session_events=self._host_session_events,
            agent_host_capabilities=self._agent_host_capabilities,
            gateway_management=self._gateway_management,
            agent_host_management=self._agent_host_management,
        )
        logger.info("Starting Mabrid server on %s:%d", self._api_host, self._api_port)
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=self._api_host,
                port=self._api_port,
                access_log=False,
                log_level="info",
            )
        )
        await server.serve()
