"""Primary MCP Streamable HTTP upstream transport adapter.

The adapter connects only to the explicitly configured URL. Environment-specific address mapping
belongs to deployment configuration, not protocol transport code.
"""

import asyncio
from contextlib import AsyncExitStack

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from ..contracts import StreamableHttpUpstreamConfig, UpstreamConfig, UpstreamIdentity
from .base import BaseSessionUpstreamClient


class StreamableHttpUpstreamClient(BaseSessionUpstreamClient):
    async def connect(self, config: UpstreamConfig) -> UpstreamIdentity:
        if not isinstance(config, StreamableHttpUpstreamConfig):
            raise ValueError(
                "streamable HTTP upstream client requires streamable HTTP configuration"
            )
        if self._session is not None:
            await self.close()

        stack = AsyncExitStack()
        try:
            http_client = await stack.enter_async_context(
                httpx.AsyncClient(
                    headers=config.headers or None,
                    trust_env=False,
                    timeout=httpx.Timeout(config.timeout_seconds),
                )
            )
            read_stream, write_stream, _ = await stack.enter_async_context(
                streamable_http_client(str(config.url), http_client=http_client)
            )
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            try:
                result = await asyncio.wait_for(
                    session.initialize(), timeout=config.timeout_seconds
                )
            except asyncio.TimeoutError:
                raise RuntimeError(
                    f"Timed out waiting for upstream MCP server to respond to 'initialize' "
                    f"at '{config.url}'. The server accepted the connection but did not "
                    f"complete the MCP handshake within {config.timeout_seconds:.0f} seconds. "
                    f"Verify that the upstream server is running and supports Streamable HTTP."
                ) from None
        except Exception:
            await stack.aclose()
            raise

        self._stack = stack
        self._session = session
        return self._map_initialize_result(result)
