"""MCP Python SDK upstream transport connectors."""

from __future__ import annotations

import asyncio
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from pydantic import AnyUrl

from .plans import (
    SseUpstreamConfig,
    StdioUpstreamConfig,
    StreamableHttpUpstreamConfig,
    UpstreamConfig,
)
from .protocol import (
    AppResource,
    ResourceDescriptor,
    ToolCallResult,
    ToolDescriptor,
    UpstreamIdentity,
)
from .runtime import UpstreamClient


class UpstreamClientFactory(Protocol):
    def create(self, config: UpstreamConfig) -> UpstreamClient: ...


class DefaultUpstreamClientFactory:
    def create(self, config: UpstreamConfig) -> UpstreamClient:
        return build_upstream_client(config)


class BaseSessionUpstreamClient:
    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def list_tools(self) -> list[ToolDescriptor]:
        session = self._require_session()
        result = await session.list_tools()
        return [self._map_tool(tool) for tool in result.tools]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        session = self._require_session()
        result = await session.call_tool(tool_name, arguments=arguments)
        return ToolCallResult(
            content=tuple(self._dump_model_or_value(item) for item in result.content),
            structured_content=self._dump_model_or_none(result.structuredContent),
            is_error=result.isError,
            metadata=self._dump_model_or_none(result.meta) or {},
        )

    async def list_resources(self) -> list[ResourceDescriptor]:
        session = self._require_session()
        result = await session.list_resources()
        return [self._map_resource(resource) for resource in result.resources]

    async def read_resource(self, uri: str) -> AppResource:
        session = self._require_session()
        result = await session.read_resource(AnyUrl(uri))
        if not result.contents:
            raise ValueError(f"Upstream MCP server returned no contents for resource '{uri}'")

        primary = result.contents[0]
        metadata = self._dump_model_or_none(getattr(primary, "meta", None)) or {}
        if len(result.contents) > 1:
            metadata = {**metadata, "additional_contents": len(result.contents) - 1}

        return AppResource(
            uri=str(primary.uri),
            mime_type=getattr(primary, "mimeType", "application/octet-stream"),
            text=getattr(primary, "text", None),
            blob=getattr(primary, "blob", None),
            metadata=metadata,
        )

    async def close(self) -> None:
        stack = self._stack
        self._stack = None
        self._session = None
        if stack is not None:
            await stack.aclose()

    def _require_session(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError("Upstream MCP session is not connected")
        return self._session

    def _map_initialize_result(self, result: Any) -> UpstreamIdentity:
        capabilities = self._dump_model_or_none(result.capabilities) or {}
        server_info = self._dump_model_or_none(result.serverInfo) or {}
        return UpstreamIdentity(
            server_name=server_info.get("name", "unknown-server"),
            server_version=server_info.get("version"),
            protocol_version=result.protocolVersion,
            instructions=result.instructions,
            supports_tools="tools" in capabilities,
            supports_resources="resources" in capabilities,
            raw_capabilities=capabilities,
        )

    def _map_tool(self, tool: Any) -> ToolDescriptor:
        metadata = self._dump_model_or_none(getattr(tool, "meta", None)) or {}
        annotations = self._dump_model_or_none(getattr(tool, "annotations", None)) or {}
        return ToolDescriptor(
            name=tool.name,
            title=getattr(tool, "title", None),
            description=getattr(tool, "description", None),
            input_schema=self._dump_model_or_none(getattr(tool, "inputSchema", None)) or {},
            output_schema=self._dump_model_or_none(getattr(tool, "outputSchema", None)),
            annotations=annotations,
            ui_resource_uri=self._extract_ui_resource_uri(metadata),
            metadata=metadata,
        )

    def _map_resource(self, resource: Any) -> ResourceDescriptor:
        metadata = self._dump_model_or_none(getattr(resource, "meta", None)) or {}
        annotations = self._dump_model_or_none(getattr(resource, "annotations", None)) or {}
        return ResourceDescriptor(
            name=resource.name,
            uri=str(resource.uri),
            title=getattr(resource, "title", None),
            description=getattr(resource, "description", None),
            mime_type=getattr(resource, "mimeType", None),
            annotations=annotations,
            metadata=metadata,
            size=getattr(resource, "size", None),
        )

    def _extract_ui_resource_uri(self, metadata: dict[str, Any]) -> str | None:
        candidates = [
            metadata.get("openai/outputTemplate"),
            metadata.get("openai/resourceUri"),
            metadata.get("ui"),
            metadata.get("_meta", {}).get("ui")
            if isinstance(metadata.get("_meta"), dict)
            else None,
            metadata.get("openai"),
        ]
        for candidate in candidates:
            if isinstance(candidate, str) and candidate:
                return candidate
            if not isinstance(candidate, dict):
                continue
            resource_uri = candidate.get("resourceUri") or candidate.get("outputTemplate")
            if isinstance(resource_uri, str) and resource_uri:
                return resource_uri
        return None

    def _dump_model_or_none(self, value: Any) -> Any:
        if value is None:
            return None
        return self._dump_model_or_value(value)

    def _dump_model_or_value(self, value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return value


class StdioUpstreamClient(BaseSessionUpstreamClient):
    async def connect(self, config: UpstreamConfig) -> UpstreamIdentity:
        if not isinstance(config, StdioUpstreamConfig):
            raise ValueError("stdio upstream client requires stdio configuration")
        if self._session is not None:
            await self.close()

        stack = AsyncExitStack()
        try:
            server = StdioServerParameters(
                command=config.command,
                args=list(config.args),
                cwd=str(config.cwd) if config.cwd is not None else None,
                env=config.env or None,
            )
            read_stream, write_stream = await stack.enter_async_context(stdio_client(server))
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            result = await session.initialize()
        except Exception:
            await stack.aclose()
            raise

        self._stack = stack
        self._session = session
        return self._map_initialize_result(result)


class SseUpstreamClient(BaseSessionUpstreamClient):
    async def connect(self, config: UpstreamConfig) -> UpstreamIdentity:
        if not isinstance(config, SseUpstreamConfig):
            raise ValueError("SSE upstream client requires SSE configuration")
        if self._session is not None:
            await self.close()

        stack = AsyncExitStack()
        try:
            read_stream, write_stream = await stack.enter_async_context(
                sse_client(str(config.url), headers=config.headers or None)
            )
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            result = await session.initialize()
        except Exception:
            await stack.aclose()
            raise

        self._stack = stack
        self._session = session
        return self._map_initialize_result(result)


class StreamableHttpUpstreamClient(BaseSessionUpstreamClient):
    async def connect(self, config: UpstreamConfig) -> UpstreamIdentity:
        if not isinstance(config, StreamableHttpUpstreamConfig):
            raise ValueError(
                "streamable HTTP upstream client requires streamable HTTP configuration"
            )
        if self._session is not None:
            await self.close()

        stack = AsyncExitStack()
        try:
            http_client = await stack.enter_async_context(
                httpx.AsyncClient(
                    headers=config.headers or None,
                    trust_env=False,
                    timeout=httpx.Timeout(config.timeout_seconds),
                )
            )
            selected_url = await self._select_url(http_client, str(config.url))
            read_stream, write_stream, _ = await stack.enter_async_context(
                streamable_http_client(selected_url, http_client=http_client)
            )
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            try:
                result = await asyncio.wait_for(
                    session.initialize(), timeout=config.timeout_seconds
                )
            except asyncio.TimeoutError:
                raise RuntimeError(
                    f"Timed out waiting for upstream MCP server to respond to 'initialize' "
                    f"at '{selected_url}'. The server accepted the connection but did not "
                    f"complete the MCP handshake within {config.timeout_seconds:.0f} seconds. "
                    f"Verify that the upstream server is running and supports Streamable HTTP."
                ) from None
        except Exception:
            await stack.aclose()
            raise

        self._stack = stack
        self._session = session
        return self._map_initialize_result(result)

    async def _select_url(self, http_client: httpx.AsyncClient, configured_url: str) -> str:
        errors: list[str] = []
        for candidate in self._iter_url_candidates(configured_url):
            try:
                await http_client.options(
                    candidate,
                    follow_redirects=True,
                    timeout=httpx.Timeout(connect=2.0, read=2.0, write=2.0, pool=2.0),
                )
                return candidate
            except (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
            ) as exc:
                errors.append(f"{candidate}: {exc}")

        joined_errors = "; ".join(errors) if errors else "no candidates generated"
        raise RuntimeError(
            f"Unable to reach streamable HTTP upstream at '{configured_url}'. Attempts: {joined_errors}"
        )

    def _iter_url_candidates(self, configured_url: str) -> list[str]:
        candidates = [configured_url]
        parts = urlsplit(configured_url)
        if parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return candidates

        for host in self._localhost_fallback_hosts():
            candidate = self._replace_host(parts, host)
            if candidate not in candidates:
                candidates.append(candidate)
        return candidates

    def _localhost_fallback_hosts(self) -> list[str]:
        hosts: list[str] = []
        if self._running_in_wsl():
            gateway = self._read_wsl_gateway()
            if gateway is not None:
                hosts.append(gateway)
        hosts.append("host.docker.internal")
        return hosts

    def _running_in_wsl(self) -> bool:
        if "WSL_DISTRO_NAME" in os.environ:
            return True
        try:
            version = Path("/proc/version").read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False
        return "microsoft" in version.lower()

    def _read_wsl_gateway(self) -> str | None:
        resolv_conf = Path("/etc/resolv.conf")
        try:
            for line in resolv_conf.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not line.startswith("nameserver "):
                    continue
                _, _, value = line.partition(" ")
                host = value.strip()
                if host:
                    return host
        except OSError:
            return None
        return None

    def _replace_host(self, parts: SplitResult, host: str) -> str:
        port = f":{parts.port}" if parts.port is not None else ""
        netloc = f"{host}{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def build_upstream_client(config: UpstreamConfig) -> UpstreamClient:
    if isinstance(config, StdioUpstreamConfig):
        return StdioUpstreamClient()
    if isinstance(config, SseUpstreamConfig):
        return SseUpstreamClient()
    if isinstance(config, StreamableHttpUpstreamConfig):
        return StreamableHttpUpstreamClient()
    raise TypeError(f"Unsupported upstream config: {type(config).__name__}")
