"""Backend entry points for the mcpapps bridge host."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import anyio

from mcpapps_bridge.bootstrap import bootstrap_gateway
from mcpapps_bridge.config import ConfigError, resolve_runtime_configuration
from mcpapps_bridge.host import BridgeHostRuntime
from mcpapps_bridge.logging import LogMode, configure_logging, get_logger

logger = get_logger(__name__)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the mcpapps bridge backend.")
    parser.add_argument("--config")
    parser.add_argument("--upstream")
    parser.add_argument("--api-host")
    parser.add_argument("--api-port", type=int)
    parser.add_argument("--proxy-name")
    parser.add_argument("--httpx-timeout", type=float, dest="httpx_timeout_seconds")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_arg_parser().parse_args(argv)


async def serve_runtime(args: argparse.Namespace) -> None:
    configuration = resolve_runtime_configuration(
        args.config,
        upstream_name=args.upstream,
        api_host=args.api_host,
        api_port=args.api_port,
        proxy_name=args.proxy_name,
        httpx_timeout_seconds=args.httpx_timeout_seconds,
    )
    logger.info("Configuration loaded from %s", configuration.config_path)
    logger.info(
        "API listening on %s:%d", configuration.bridge.api_host, configuration.bridge.api_port
    )
    logger.info("Storage path: %s", configuration.storage.sqlite_path)
    logger.info("Upstreams: %s", ", ".join(configuration.upstreams) or "(none)")

    result = await bootstrap_gateway(configuration)

    api_host = configuration.bridge.api_host
    api_port = configuration.bridge.api_port
    for published in result.manager.published_endpoints:
        slug = published.revision.slug
        streamable_url = f"http://{api_host}:{api_port}/mcp/{slug}"
        sse_url = f"http://{api_host}:{api_port}/mcp/{slug}/sse"
        logger.info(
            "MCP endpoint URL: %s (streamable-http, recommended) | %s (SSE)",
            streamable_url,
            sse_url,
        )

    runtime = BridgeHostRuntime(
        result.manager,
        api_host=configuration.bridge.api_host,
        api_port=configuration.bridge.api_port,
    )
    try:
        await runtime.serve()
    finally:
        await result.storage.close()


def main() -> None:
    """Run the bridge runtime from YAML configuration."""
    configure_logging(LogMode.PRODUCTION)
    args = parse_args()
    try:
        anyio.run(serve_runtime, args)
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
