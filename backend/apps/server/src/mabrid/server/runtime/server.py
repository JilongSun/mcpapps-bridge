"""Uvicorn process runtime for the composed Mabrid HTTP application.

This outer shell owns listener configuration and process serving only. FastAPI composition and
application lifecycles remain delegated to the API and Gateway services.
"""

from __future__ import annotations

import uvicorn
from mabrid.application.agent_host import AgentHostService
from mabrid.application.gateway.sessions import GatewaySessionCoordinator

from mabrid.server.api import create_app
from mabrid.server.logging import get_logger

logger = get_logger(__name__)


class MabridServerRuntime:
    def __init__(
        self,
        gateway: GatewaySessionCoordinator,
        *,
        agent_host: AgentHostService | None = None,
        api_host: str = "127.0.0.1",
        api_port: int = 8765,
    ) -> None:
        self._gateway = gateway
        self._agent_host = agent_host
        self._api_host = api_host
        self._api_port = api_port

    async def serve(self) -> None:
        app = create_app(self._gateway, agent_host=self._agent_host)
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
