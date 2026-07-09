"""Runtime orchestration for the downstream HTTP/SSE proxy and control plane."""

from __future__ import annotations

import uvicorn

from mcpapps_bridge.api import create_app
from mcpapps_bridge.mcp import BridgeManager


class BridgeHostRuntime:
    def __init__(
        self,
        manager: BridgeManager,
        *,
        api_host: str = "127.0.0.1",
        api_port: int = 8765,
    ) -> None:
        self._manager = manager
        self._api_host = api_host
        self._api_port = api_port

    async def serve(self) -> None:
        app = create_app(self._manager)
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
