"""Abstract and concrete upstream MCP client implementations."""

from __future__ import annotations

import asyncio
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from pydantic import AnyUrl
from pydantic import BaseModel, Field

from mcpapps_bridge.models import (
    AppResource,
    ResourceDescriptor,
    ToolCallResult,
    ToolDescriptor,
    UpstreamInitialization,
)


class UpstreamServerConfig(BaseModel):
    transport: Literal["stdio", "sse", "streamable-http"] = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: Path | None = None
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    httpx_timeout_seconds: float | None = None


class UpstreamMcpClient(Protocol):
    async def connect(self, config: UpstreamServerConfig) -> UpstreamInitialization: ...

    async def list_tools(self) -> list[ToolDescriptor]: ...

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult: ...

    async def list_resources(self) -> list[ResourceDescriptor]: ...

    async def read_resource(self, uri: str) -> AppResource: ...

    async def close(self) -> None: ...


class BaseSessionUpstreamMcpClient:
    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._config: UpstreamServerConfig | None = None

    async def list_tools(self) -> list[ToolDescriptor]:
        session = self._require_session()
        result = await session.list_tools()
        return [self._map_tool(tool) for tool in result.tools]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        session = self._require_session()
        result = await session.call_tool(tool_name, arguments=arguments)
        return ToolCallResult(
            content=[self._dump_model_or_value(item) for item in result.content],
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
        parsed_uri = AnyUrl(uri)
        result = await session.read_resource(parsed_uri)
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
        self._config = None
        if stack is not None:
            await stack.aclose()

    def _require_session(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError("Upstream MCP session is not connected")
        return self._session

    def _map_initialize_result(self, result: Any) -> UpstreamInitialization:
        capabilities = self._dump_model_or_none(result.capabilities) or {}
        server_info = self._dump_model_or_none(result.serverInfo) or {}
        return UpstreamInitialization(
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


class StdioUpstreamMcpClient(BaseSessionUpstreamMcpClient):
    async def connect(self, config: UpstreamServerConfig) -> UpstreamInitialization:
        if config.command is None:
            raise ValueError("stdio upstream transport requires a command")
        if self._session is not None:
            await self.close()

        stack = AsyncExitStack()
        try:
            server = StdioServerParameters(
                command=config.command,
                args=config.args,
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
        self._config = config
        return self._map_initialize_result(result)


class SseUpstreamMcpClient(BaseSessionUpstreamMcpClient):
    async def connect(self, config: UpstreamServerConfig) -> UpstreamInitialization:
        if config.url is None:
            raise ValueError("sse upstream transport requires a URL")
        if self._session is not None:
            await self.close()

        stack = AsyncExitStack()
        try:
            read_stream, write_stream = await stack.enter_async_context(
                sse_client(config.url, headers=config.headers or None)
            )
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            result = await session.initialize()
        except Exception:
            await stack.aclose()
            raise

        self._stack = stack
        self._session = session
        self._config = config
        return self._map_initialize_result(result)


class StreamableHttpUpstreamMcpClient(BaseSessionUpstreamMcpClient):
    async def connect(self, config: UpstreamServerConfig) -> UpstreamInitialization:
        if config.url is None:
            raise ValueError("streamable-http upstream transport requires a URL")
        if self._session is not None:
            await self.close()

        stack = AsyncExitStack()
        try:
            client_timeout = (
                httpx.Timeout(config.httpx_timeout_seconds)
                if config.httpx_timeout_seconds is not None
                else httpx.Timeout(30.0)
            )
            http_client = await stack.enter_async_context(
                httpx.AsyncClient(
                    headers=config.headers or None, trust_env=False, timeout=client_timeout
                )
            )
            selected_url = await self._select_url(http_client, config.url)
            read_stream, write_stream, _ = await stack.enter_async_context(
                streamable_http_client(selected_url, http_client=http_client)
            )
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            initialize_timeout = (
                config.httpx_timeout_seconds if config.httpx_timeout_seconds is not None else 30.0
            )
            try:
                result = await asyncio.wait_for(session.initialize(), timeout=initialize_timeout)
            except asyncio.TimeoutError:
                raise RuntimeError(
                    f"Timed out waiting for upstream MCP server to respond to 'initialize' "
                    f"at '{selected_url}'. The server accepted the connection but did not "
                    f"complete the MCP handshake within {initialize_timeout:.0f} seconds. "
                    f"Verify that the upstream server is running and supports Streamable HTTP."
                ) from None
        except Exception:
            await stack.aclose()
            raise

        self._stack = stack
        self._session = session
        self._config = config.model_copy(update={"url": selected_url})
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


def build_upstream_client(config: UpstreamServerConfig) -> UpstreamMcpClient:
    if config.transport == "stdio":
        return StdioUpstreamMcpClient()
    if config.transport == "sse":
        return SseUpstreamMcpClient()
    if config.transport == "streamable-http":
        return StreamableHttpUpstreamMcpClient()
    raise ValueError(f"Unsupported upstream transport: {config.transport}")
