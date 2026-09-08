"""Select a fresh upstream transport adapter for one bridge binding."""

from typing import Protocol

from ..contracts import (
    SseUpstreamConfig,
    StdioUpstreamConfig,
    StreamableHttpUpstreamConfig,
    UpstreamConfig,
)
from .runtime import UpstreamClient
from .sse import SseUpstreamClient
from .stdio import StdioUpstreamClient
from .streamable_http import StreamableHttpUpstreamClient


class UpstreamClientFactory(Protocol):
    def create(self, config: UpstreamConfig) -> UpstreamClient: ...


class DefaultUpstreamClientFactory:
    def create(self, config: UpstreamConfig) -> UpstreamClient:
        return build_upstream_client(config)


def build_upstream_client(config: UpstreamConfig) -> UpstreamClient:
    if isinstance(config, StdioUpstreamConfig):
        return StdioUpstreamClient()
    if isinstance(config, SseUpstreamConfig):
        return SseUpstreamClient()
    if isinstance(config, StreamableHttpUpstreamConfig):
        return StreamableHttpUpstreamClient()
    raise TypeError(f"Unsupported upstream config: {type(config).__name__}")
