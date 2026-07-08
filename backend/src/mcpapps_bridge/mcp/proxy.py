"""Bridge proxy assembly helpers."""

from __future__ import annotations

from mcpapps_bridge.session import BridgeSessionState

from .downstream import BridgeDownstreamServer
from .runtime import BridgeRuntime
from .upstream import UpstreamMcpClient, UpstreamServerConfig


def build_proxy_server(
    upstream_config: UpstreamServerConfig,
    session_state: BridgeSessionState,
    *,
    name: str = "mcpapps-proxy",
    version: str = "0.1.0",
    upstream_client: UpstreamMcpClient | None = None,
) -> BridgeDownstreamServer:
    runtime = BridgeRuntime(
        upstream_config,
        session_state,
        name=name,
        version=version,
        upstream_client=upstream_client,
    )
    return BridgeDownstreamServer(
        runtime,
        session_state,
        name=name,
        version=version,
    )
