"""Bridge proxy assembly helpers."""

from __future__ import annotations

from mcpapps_bridge.session import BridgeSessionState

from .downstream import BridgeDownstreamServer
from .handlers import ProxyHandlers
from .manager import BridgeManager, BridgeRoute
from .runtime import UpstreamRuntime
from .upstream import UpstreamMcpClient, UpstreamServerConfig


def build_bridge_manager(
    upstream_config: UpstreamServerConfig,
    session_state: BridgeSessionState,
    *,
    name: str = "mcpapps-proxy",
    version: str = "0.1.0",
    upstream_client: UpstreamMcpClient | None = None,
) -> BridgeManager:
    runtime = UpstreamRuntime(
        upstream_config,
        session_state,
        name=name,
        version=version,
        upstream_client=upstream_client,
    )
    handlers = ProxyHandlers(runtime, session_state)
    downstream = BridgeDownstreamServer(
        handlers,
        identity_provider=lambda: runtime.identity,
        name=name,
        version=version,
    )
    route = BridgeRoute(
        route_id=name,
        path="/mcp",
        runtime=runtime,
        downstream=downstream,
        session_store=session_state,
    )
    return BridgeManager([route])
