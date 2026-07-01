"""Backend entry points for the mcpapps bridge host."""

from __future__ import annotations

import argparse
from pathlib import Path

import anyio
import uvicorn

from mcpapps_bridge.api import create_app
from mcpapps_bridge.host import BridgeHostRuntime
from mcpapps_bridge.mcp import StdioServerConfig, build_stdio_proxy_server
from mcpapps_bridge.session import BridgeSessionState

app = create_app()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the mcpapps bridge backend.")
    parser.add_argument("--api-host", default="127.0.0.1")
    parser.add_argument("--api-port", type=int, default=8765)
    parser.add_argument("--session-id", default="local-dev-session")
    parser.add_argument("--proxy-name", default="mcpapps-proxy")
    parser.add_argument("--upstream-command")
    parser.add_argument("--upstream-arg", action="append", default=[])
    parser.add_argument("--upstream-cwd")
    return parser.parse_args()


async def serve_runtime(args: argparse.Namespace) -> None:
    session_state = BridgeSessionState(session_id=args.session_id)
    upstream_config = StdioServerConfig(
        command=args.upstream_command,
        args=args.upstream_arg,
        cwd=Path(args.upstream_cwd) if args.upstream_cwd else None,
    )
    proxy_server = build_stdio_proxy_server(
        upstream_config,
        session_state,
        name=args.proxy_name,
    )
    runtime = BridgeHostRuntime(
        proxy_server,
        session_state,
        api_host=args.api_host,
        api_port=args.api_port,
    )
    await runtime.serve()


def main() -> None:
    """Run the bridge control plane or the combined proxy runtime."""
    args = parse_args()
    if args.upstream_command:
        anyio.run(serve_runtime, args)
        return

    uvicorn.run(app, host=args.api_host, port=args.api_port)


if __name__ == "__main__":
    main()
