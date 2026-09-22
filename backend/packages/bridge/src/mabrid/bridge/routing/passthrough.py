"""Transparent single-upstream routing for one bridge session."""

from __future__ import annotations

from typing import Any

from anyio.abc import TaskGroup

from ..contracts import (
    BridgeErrorRaised,
    BridgeFailure,
    BridgeFailureCode,
    BridgeObserver,
    BridgeSessionStarted,
    ReadResourceResult,
    ResourceDescriptor,
    ResourceRead,
    ToolCallResult,
    ToolDescriptor,
    ToolsPublished,
    UpstreamIdentity,
)
from ..upstream.runtime import UpstreamRuntime


class PassthroughRouter:
    def __init__(
        self,
        runtime: UpstreamRuntime,
        observer: BridgeObserver,
        session_key: str,
        worker_task_group: TaskGroup,
    ) -> None:
        self._runtime = runtime
        self._observer = observer
        self._session_key = session_key
        self._worker_task_group = worker_task_group

    @property
    def identity(self) -> UpstreamIdentity:
        return self._runtime.identity

    async def start(self) -> None:
        await self._runtime.start_worker(self._worker_task_group)
        try:
            await self._runtime.start()
            await self._observer.observe(
                BridgeSessionStarted(
                    session_key=self._session_key,
                    identity=self._runtime.identity,
                )
            )
            await self.list_tools()
            await self.list_resources()
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        await self._runtime.shutdown_worker()

    async def list_tools(self) -> list[ToolDescriptor]:
        tools = await self._runtime.refresh_tools()
        await self._observer.observe(
            ToolsPublished(session_key=self._session_key, tools=tuple(tools))
        )
        return tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolCallResult:
        return await self._runtime.call_tool(tool_name, arguments)

    async def load_tool_resource(self, tool_name: str, operation_key: str) -> None:
        tool = self._runtime.tool(tool_name)
        if tool is None or tool.ui_resource_uri is None:
            return
        try:
            await self._read_resource(tool.ui_resource_uri, operation_key=operation_key)
        except Exception as exc:
            await self._observer.observe(
                BridgeErrorRaised(
                    session_key=self._session_key,
                    operation="application_resource_load",
                    operation_key=operation_key,
                    failure=BridgeFailure(
                        code=BridgeFailureCode.UPSTREAM_PROTOCOL,
                        message=f"Failed to load UI resource for tool '{tool_name}'",
                        details={"reason": str(exc)},
                    ),
                )
            )

    async def list_resources(self) -> list[ResourceDescriptor]:
        return await self._runtime.refresh_resources()

    async def read_resource(self, uri: str) -> ReadResourceResult:
        return await self._read_resource(uri)

    async def _read_resource(
        self,
        uri: str,
        *,
        operation_key: str | None = None,
    ) -> ReadResourceResult:
        result = await self._runtime.read_resource(uri)
        await self._observer.observe(
            ResourceRead(
                session_key=self._session_key,
                operation_key=operation_key,
                requested_uri=uri,
                result=result,
            )
        )
        return result
