"""Runtime orchestration for the stdio proxy and HTTP control plane."""

from __future__ import annotations

import anyio
import uvicorn

from mcpapps_bridge.api import create_app
from mcpapps_bridge.mcp import StdioProxyServer
from mcpapps_bridge.session import BridgeSessionState


class BridgeHostRuntime:
    def __init__(
        self,
        proxy_server: StdioProxyServer,
        session_state: BridgeSessionState,
        *,
        api_host: str = "127.0.0.1",
        api_port: int = 8765,
    ) -> None:
        self._proxy_server = proxy_server
        self._session_state = session_state
        self._api_host = api_host
        self._api_port = api_port

    async def serve(self) -> None:
        app = create_app(self._session_state)
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=self._api_host,
                port=self._api_port,
                access_log=False,
                log_level="info",
            )
        )

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(server.serve)
            try:
                await self._proxy_server.serve()
            finally:
                server.should_exit = True
