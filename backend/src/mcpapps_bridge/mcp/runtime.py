"""Single-upstream MCP session runtime state and behavior."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import anyio
from anyio.abc import TaskGroup, TaskStatus
from anyio.streams.memory import MemoryObjectSendStream

from mcpapps_bridge.logging import get_logger
from mcpapps_bridge.models import (
    AppResource,
    ResourceDescriptor,
    ToolCallResult,
    ToolDescriptor,
    UpstreamInitialization,
)
from .upstream import UpstreamMcpClient, UpstreamServerConfig, build_upstream_client

logger = get_logger(__name__)

CommandResult = TypeVar("CommandResult")


@dataclass
class _CommandOutcome(Generic[CommandResult]):
    value: CommandResult | None = None
    error: Exception | None = None


@dataclass
class _RuntimeCommand(Generic[CommandResult]):
    operation: str
    execute: Callable[[], Awaitable[CommandResult]]
    response: MemoryObjectSendStream[_CommandOutcome[CommandResult]]


@dataclass
class _ShutdownCommand:
    response: MemoryObjectSendStream[_CommandOutcome[None]]


RuntimeMessage = _RuntimeCommand[Any] | _ShutdownCommand


class UpstreamRuntime:
    """Owns upstream lifecycle, state synchronization, and bridge-side caches."""

    def __init__(
        self,
        upstream_config: UpstreamServerConfig,
        *,
        name: str,
        version: str,
        upstream_client: UpstreamMcpClient | None = None,
    ) -> None:
        self._upstream_config = upstream_config
        self._name = name
        self._version = version
        self._upstream_client = upstream_client or build_upstream_client(upstream_config)
        self._tool_cache: dict[str, ToolDescriptor] = {}
        self._resource_cache: dict[str, AppResource] = {}
        self._resource_descriptors: dict[str, ResourceDescriptor] = {}
        self._upstream_identity = UpstreamInitialization(server_name=name, server_version=version)
        self._started = False
        self._worker_running = False
        self._command_send, self._command_receive = anyio.create_memory_object_stream[
            RuntimeMessage
        ](0)

    @property
    def identity(self) -> UpstreamInitialization:
        return self._upstream_identity

    async def start_worker(self, task_group: TaskGroup) -> None:
        if self._worker_running:
            return
        await task_group.start(self._run_worker)

    async def shutdown_worker(self) -> None:
        if not self._worker_running:
            return
        response_send, response_receive = anyio.create_memory_object_stream[_CommandOutcome[None]](
            1
        )
        await self._command_send.send(_ShutdownCommand(response=response_send))
        outcome = await response_receive.receive()
        if outcome.error is not None:
            raise outcome.error

    async def start(self) -> None:
        await self._submit("connect", self._connect)

    async def close(self) -> None:
        await self._submit("disconnect", self._disconnect)

    async def refresh_tools(self) -> list[ToolDescriptor]:
        async def refresh() -> list[ToolDescriptor]:
            tools = await self._upstream_client.list_tools()
            self._tool_cache = {tool.name: tool for tool in tools}
            return tools

        return await self._submit("tools/list", refresh)

    async def refresh_resources(self) -> list[ResourceDescriptor]:
        async def refresh() -> list[ResourceDescriptor]:
            try:
                resources = await self._upstream_client.list_resources()
            except Exception:
                resources = self._synthesized_resources_from_tools()
            self._resource_descriptors = {resource.uri: resource for resource in resources}
            return resources

        return await self._submit("resources/list", refresh)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        return await self._submit(
            "tools/call",
            lambda: self._upstream_client.call_tool(tool_name, arguments),
        )

    def tool(self, tool_name: str) -> ToolDescriptor | None:
        return self._tool_cache.get(tool_name)

    async def preload_tool_resource(self, tool_name: str) -> None:
        tool = self._tool_cache.get(tool_name)
        if tool is None or tool.ui_resource_uri is None:
            return
        await self.read_and_cache_resource(tool.ui_resource_uri)

    async def read_and_cache_resource(self, uri: str) -> AppResource:
        cached = self._resource_cache.get(uri)
        if cached is not None:
            return cached

        async def read() -> AppResource:
            resource = await self._upstream_client.read_resource(uri)
            self._resource_cache[uri] = resource
            return resource

        return await self._submit("resources/read", read)

    async def _run_worker(
        self,
        *,
        task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        if self._worker_running:
            raise RuntimeError(f"Upstream worker is already running: {self._name}")
        self._worker_running = True
        task_status.started()
        try:
            async with self._command_receive:
                async for command in self._command_receive:
                    if isinstance(command, _ShutdownCommand):
                        await self._complete_shutdown(command)
                        return
                    await self._execute_command(command)
        finally:
            # MCP SDK transports contain AnyIO cancel scopes and must be closed by
            # the same persistent task that entered their context managers.
            try:
                await self._disconnect()
            finally:
                self._worker_running = False

    async def _execute_command(self, command: _RuntimeCommand[Any]) -> None:
        try:
            outcome = _CommandOutcome(value=await command.execute())
        except Exception as exc:
            outcome = _CommandOutcome(error=exc)
        await command.response.send(outcome)

    async def _complete_shutdown(self, command: _ShutdownCommand) -> None:
        try:
            await self._disconnect()
            outcome = _CommandOutcome[None]()
        except Exception as exc:
            outcome = _CommandOutcome[None](error=exc)
        await command.response.send(outcome)

    async def _submit(
        self,
        operation: str,
        execute: Callable[[], Awaitable[CommandResult]],
    ) -> CommandResult:
        if not self._worker_running:
            raise RuntimeError(f"Upstream worker is not running: {self._name}")
        response_send, response_receive = anyio.create_memory_object_stream[
            _CommandOutcome[CommandResult]
        ](1)
        await self._command_send.send(
            _RuntimeCommand(operation=operation, execute=execute, response=response_send)
        )
        outcome = await response_receive.receive()
        if outcome.error is not None:
            raise outcome.error
        return outcome.value  # type: ignore[return-value]

    async def _connect(self) -> None:
        if self._started:
            return
        logger.info(
            "Connecting upstream: name=%s transport=%s",
            self._name,
            self._upstream_config.transport,
        )
        if self._upstream_config.transport == "stdio":
            logger.debug(
                "  stdio: command=%s args=%s",
                self._upstream_config.command,
                self._upstream_config.args,
            )
        else:
            logger.debug("  http: url=%s", self._upstream_config.url)
        try:
            upstream = await self._upstream_client.connect(self._upstream_config)
        except Exception:
            logger.exception(
                "Failed to connect upstream: name=%s transport=%s",
                self._name,
                self._upstream_config.transport,
            )
            raise RuntimeError(
                f"Failed to connect to upstream MCP server "
                f"(transport={self._upstream_config.transport}). "
                f"Check that the upstream server is running and the bridge configuration is correct."
            ) from None
        self._upstream_identity = upstream
        self._started = True
        logger.info(
            "Upstream connected: name=%s identity=%s",
            self._name,
            upstream.model_dump_json(),
        )

    async def _disconnect(self) -> None:
        if not self._started:
            return
        try:
            await self._upstream_client.close()
        finally:
            self._started = False
            self._upstream_identity = UpstreamInitialization(
                server_name=self._name,
                server_version=self._version,
            )

    def _synthesized_resources_from_tools(self) -> list[ResourceDescriptor]:
        resources: list[ResourceDescriptor] = []
        for tool in self._tool_cache.values():
            if tool.ui_resource_uri is None:
                continue
            resources.append(
                ResourceDescriptor(
                    name=f"{tool.name}_ui",
                    uri=tool.ui_resource_uri,
                    title=tool.title,
                    description=f"UI resource for tool '{tool.name}'",
                    mime_type="text/html;profile=mcp-app",
                )
            )
        return resources
