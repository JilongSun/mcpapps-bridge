"""Bridge manager and route lifecycle orchestration."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

from mcpapps_bridge.session import BridgeSessionStore

from .downstream import BridgeDownstreamServer
from .runtime import UpstreamRuntime


@dataclass(frozen=True)
class BridgeRoute:
    route_id: str
    path: str
    runtime: UpstreamRuntime
    downstream: BridgeDownstreamServer
    session_store: BridgeSessionStore


class BridgeManager:
    """Owns bridge routes, lifecycle, and route-level session stores."""

    def __init__(self, routes: list[BridgeRoute]) -> None:
        if not routes:
            raise ValueError("BridgeManager requires at least one route")
        self._routes = routes

    @property
    def routes(self) -> list[BridgeRoute]:
        return list(self._routes)

    @property
    def default_route(self) -> BridgeRoute:
        return self._routes[0]

    @asynccontextmanager
    async def lifecycle(self) -> AsyncIterator[None]:
        await self.start()
        try:
            async with self.run_http_transports():
                yield
        finally:
            await self.close()

    async def start(self) -> None:
        for route in self._routes:
            await route.runtime.start()

    async def close(self) -> None:
        for route in reversed(self._routes):
            await route.runtime.close()

    @asynccontextmanager
    async def run_http_transports(self) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            for route in self._routes:
                await stack.enter_async_context(route.downstream.run_http_transports())
            yield
