"""Debug entry point — edit the COMMAND string below to switch upstream configs."""

from __future__ import annotations

import shlex

import anyio
import uvicorn

from mcpapps_bridge.api import create_app
from mcpapps_bridge.host import BridgeHostRuntime
from mcpapps_bridge.main import build_arg_parser, build_upstream_config
from mcpapps_bridge.session import BridgeSessionState

# ── Edit this string to change upstream config ──────────────────────────
# Copy the `uv run ...` command you normally use below.
# `uv run python -m mcpapps_bridge.main` prefix is stripped automatically.
_COMMAND = """
    --upstream-transport streamable-http
    --upstream-url http://localhost:8760/mcp
    --proxy-name enterprise-ops-hub-proxy
    --api-port 8767
"""

# ── Debug timeout (seconds) — set to 0 for no timeout ───────────────────
_DEBUG_HTTPX_TIMEOUT: float = 3600


def _parse_command(command: str) -> list[str]:
    """Split a shell command string into argv, skipping the uv/python prefix."""
    tokens = shlex.split(command, comments=True)
    # Strip `uv run python -m mcpapps_bridge.main` (or `debug_main`) prefix
    skip = 0
    for i, token in enumerate(tokens):
        if token in ("python", "python3"):
            skip = i + 1
        if token.endswith("main") or token.endswith("debug_main"):
            skip = i + 1
    return tokens[skip:]


async def run() -> None:
    argv = _parse_command(_COMMAND)
    parser = build_arg_parser()
    parser.description = "Debug bridge runtime (edit _COMMAND in debug_main.py to change config)."
    args = parser.parse_args(argv)

    session_state = BridgeSessionState(session_id=args.session_id)
    upstream_config = build_upstream_config(args)
    upstream_config.httpx_timeout_seconds = _DEBUG_HTTPX_TIMEOUT
    from mcpapps_bridge.mcp import build_proxy_server

    proxy = build_proxy_server(upstream_config, session_state, name=args.proxy_name)
    runtime = BridgeHostRuntime(
        proxy, session_state, api_host=args.api_host, api_port=args.api_port
    )
    await runtime.serve()


def main() -> None:
    anyio.run(run)


if __name__ == "__main__":
    main()
