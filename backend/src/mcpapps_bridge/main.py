"""Backend entry points for the mcpapps bridge host."""

from __future__ import annotations

import argparse
from pathlib import Path
from collections.abc import Sequence

import anyio
import uvicorn

from mcpapps_bridge.api import create_app
from mcpapps_bridge.host import BridgeHostRuntime
from mcpapps_bridge.mcp import UpstreamServerConfig, build_proxy_server
from mcpapps_bridge.session import BridgeSessionState

app = create_app()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the mcpapps bridge backend.")
    parser.add_argument("--api-host", default="127.0.0.1")
    parser.add_argument("--api-port", type=int, default=8765)
    parser.add_argument("--session-id", default="local-dev-session")
    parser.add_argument("--proxy-name", default="mcpapps-proxy")
    parser.add_argument(
        "--upstream-transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
    )
    parser.add_argument("--upstream-command")
    parser.add_argument("--upstream-arg", action="append", default=[])
    parser.add_argument("--upstream-cwd")
    parser.add_argument("--upstream-env", action="append", default=[], dest="upstream_env")
    parser.add_argument("--upstream-url")
    parser.add_argument("--upstream-header", action="append", default=[], dest="upstream_headers")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_arg_parser().parse_args(argv)


def parse_key_value_items(items: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            continue
        key, _, value = item.partition("=")
        values[key] = value
    return values


def build_upstream_config(args: argparse.Namespace) -> UpstreamServerConfig:
    return UpstreamServerConfig(
        transport=args.upstream_transport,
        command=args.upstream_command,
        args=args.upstream_arg,
        cwd=Path(args.upstream_cwd) if args.upstream_cwd else None,
        env=parse_key_value_items(args.upstream_env),
        url=args.upstream_url,
        headers=parse_key_value_items(args.upstream_headers),
    )


async def serve_runtime(args: argparse.Namespace) -> None:
    session_state = BridgeSessionState(session_id=args.session_id)
    upstream_config = build_upstream_config(args)
    proxy_server = build_proxy_server(
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
    if args.upstream_transport == "stdio" and args.upstream_command:
        anyio.run(serve_runtime, args)
        return

    if args.upstream_transport in {"sse", "streamable-http"} and args.upstream_url:
        anyio.run(serve_runtime, args)
        return

    uvicorn.run(app, host=args.api_host, port=args.api_port)


if __name__ == "__main__":
    main()
