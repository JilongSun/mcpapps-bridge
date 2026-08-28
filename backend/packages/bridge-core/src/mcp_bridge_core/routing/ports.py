"""Lifecycle and MCP method contract implemented by one session router."""

from typing import Protocol

from ..contracts import McpMethodRouter, UpstreamIdentity


class McpSessionRouter(McpMethodRouter, Protocol):
    @property
    def identity(self) -> UpstreamIdentity: ...

    async def start(self) -> None: ...

    async def close(self) -> None: ...
