"""MCP stdio upstream transport adapter."""

from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ..contracts import StdioUpstreamConfig, UpstreamConfig, UpstreamIdentity
from .base import BaseSessionUpstreamClient


class StdioUpstreamClient(BaseSessionUpstreamClient):
    async def connect(self, config: UpstreamConfig) -> UpstreamIdentity:
        if not isinstance(config, StdioUpstreamConfig):
            raise ValueError("stdio upstream client requires stdio configuration")
        if self._session is not None:
            await self.close()

        stack = AsyncExitStack()
        try:
            server = StdioServerParameters(
                command=config.command,
                args=list(config.args),
                cwd=str(config.cwd) if config.cwd is not None else None,
                env=config.env or None,
            )
            read_stream, write_stream = await stack.enter_async_context(stdio_client(server))
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            result = await session.initialize()
        except Exception:
            await stack.aclose()
            raise

        self._stack = stack
        self._session = session
        return self._map_initialize_result(result)
