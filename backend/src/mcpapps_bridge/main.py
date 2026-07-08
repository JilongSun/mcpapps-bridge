"""Backend entry points for the mcpapps bridge host."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import anyio

from mcpapps_bridge.config import ConfigError, resolve_runtime_selection
from mcpapps_bridge.host import BridgeHostRuntime
from mcpapps_bridge.mcp import build_proxy_server
from mcpapps_bridge.session import BridgeSessionState


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the mcpapps bridge backend.")
    parser.add_argument("--config")
    parser.add_argument("--upstream")
    parser.add_argument("--api-host")
    parser.add_argument("--api-port", type=int)
    parser.add_argument("--session-id")
    parser.add_argument("--proxy-name")
    parser.add_argument("--httpx-timeout", type=float, dest="httpx_timeout_seconds")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_arg_parser().parse_args(argv)


async def serve_runtime(args: argparse.Namespace) -> None:
    runtime_selection = resolve_runtime_selection(
        args.config,
        upstream_name=args.upstream,
        api_host=args.api_host,
        api_port=args.api_port,
        session_id=args.session_id,
        proxy_name=args.proxy_name,
        httpx_timeout_seconds=args.httpx_timeout_seconds,
    )
    session_state = BridgeSessionState(session_id=runtime_selection.bridge.session_id)
    proxy_server = build_proxy_server(
        runtime_selection.upstream,
        session_state,
        name=runtime_selection.bridge.proxy_name or runtime_selection.upstream_name,
    )
    runtime = BridgeHostRuntime(
        proxy_server,
        session_state,
        api_host=runtime_selection.bridge.api_host,
        api_port=runtime_selection.bridge.api_port,
    )
    await runtime.serve()


def main() -> None:
    """Run the bridge runtime from YAML configuration."""
    args = parse_args()
    try:
        anyio.run(serve_runtime, args)
    except ConfigError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
