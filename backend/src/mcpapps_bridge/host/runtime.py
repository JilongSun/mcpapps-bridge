"""Runtime orchestration for the downstream HTTP/SSE proxy and control plane."""

from __future__ import annotations

import uvicorn

from mcpapps_bridge.api import create_app
from mcpapps_bridge.mcp import BridgeProxyServer
from mcpapps_bridge.session import BridgeSessionState


class BridgeHostRuntime:
    def __init__(
        self,
        proxy_server: BridgeProxyServer,
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
        app = create_app(self._session_state, self._proxy_server)
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
