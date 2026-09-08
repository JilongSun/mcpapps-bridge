"""Legacy MCP SSE upstream compatibility adapter."""

from contextlib import AsyncExitStack

from mcp import ClientSession
from mcp.client.sse import sse_client

from ..contracts import SseUpstreamConfig, UpstreamConfig, UpstreamIdentity
from .base import BaseSessionUpstreamClient


class SseUpstreamClient(BaseSessionUpstreamClient):
    async def connect(self, config: UpstreamConfig) -> UpstreamIdentity:
        if not isinstance(config, SseUpstreamConfig):
            raise ValueError("SSE upstream client requires SSE configuration")
        if self._session is not None:
            await self.close()

        stack = AsyncExitStack()
        try:
            read_stream, write_stream = await stack.enter_async_context(
                sse_client(str(config.url), headers=config.headers or None)
            )
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            result = await session.initialize()
        except Exception:
            await stack.aclose()
            raise

        self._stack = stack
        self._session = session
        return self._map_initialize_result(result)
