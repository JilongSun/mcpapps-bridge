"""Command-line entry point for the deployable Mabrid server."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import anyio

from mabrid.server.composition import bootstrap_server
from mabrid.server.config import ConfigError, resolve_runtime_configuration
from mabrid.server.logging import LogMode, configure_logging, get_logger
from mabrid.server.runtime import MabridServerRuntime

logger = get_logger(__name__)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Mabrid server.")
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

    result = await bootstrap_server(configuration)

    api_host = configuration.bridge.api_host
    api_port = configuration.bridge.api_port
    for published in result.gateway.published_endpoints:
        slug = published.revision.slug
        streamable_url = f"http://{api_host}:{api_port}/mcp/{slug}"
        sse_url = f"http://{api_host}:{api_port}/mcp/{slug}/sse"
        logger.info(
            "MCP endpoint URL: %s (streamable-http, recommended) | %s (SSE)",
            streamable_url,
            sse_url,
        )

    runtime = MabridServerRuntime(
        result.gateway,
        agent_host=result.agent_host.service if result.agent_host is not None else None,
        api_host=configuration.bridge.api_host,
        api_port=configuration.bridge.api_port,
    )
    try:
        await runtime.serve()
    finally:
        if result.agent_host is not None:
            await result.agent_host.runtime.close()
        await result.database.close()


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
