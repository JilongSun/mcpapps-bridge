"""Public bridge engine and session lifecycle facade."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from types import TracebackType
from typing import Any, Self

import anyio
from anyio.abc import TaskGroup

from .observer import BridgeObserver
from .plans import BindingPlan, EndpointMode, EndpointPlan
from .protocol import (
    AppResource,
    ResourceDescriptor,
    ToolCallResult,
    ToolDescriptor,
    UpstreamIdentity,
)
from .router import AggregateRouter, McpSessionRouter, PassthroughRouter
from .runtime import UpstreamRuntime
from .upstream import DefaultUpstreamClientFactory, UpstreamClientFactory


class BridgeSession:
    """Owns one immutable endpoint plan and its session-scoped protocol runtime."""

    def __init__(
        self,
        session_key: str,
        plan: EndpointPlan,
        router: McpSessionRouter,
        on_closed: Callable[[BridgeSession], None],
    ) -> None:
        self.session_key = session_key
        self.plan = plan
        self._router = router
        self._on_closed = on_closed
        self._close_lock = anyio.Lock()
        self._closed = False

    @property
    def identity(self) -> UpstreamIdentity:
        return self._router.identity

    async def list_tools(self) -> list[ToolDescriptor]:
        return await self._router.list_tools()

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        return await self._router.call_tool(tool_name, arguments)

    async def preload_tool_resource(self, tool_name: str) -> None:
        await self._router.preload_tool_resource(tool_name)

    async def list_resources(self) -> list[ResourceDescriptor]:
        return await self._router.list_resources()

    async def read_resource(self, uri: str) -> AppResource:
        return await self._router.read_resource(uri)

    async def aclose(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            try:
                await self._router.close()
            finally:
                self._on_closed(self)


class BridgeEngine:
    """Owns worker tasks and opens isolated bridge sessions from immutable plans."""

    def __init__(
        self,
        *,
        client_factory: UpstreamClientFactory | None = None,
        version: str = "0.1.0",
    ) -> None:
        self._client_factory = client_factory or DefaultUpstreamClientFactory()
        self._version = version
        self._sessions: list[BridgeSession] = []
        self._session_keys: set[str] = set()
        self._lifecycle_stack: AsyncExitStack | None = None
        self._worker_task_group: TaskGroup | None = None

    async def __aenter__(self) -> Self:
        if self._lifecycle_stack is not None:
            raise RuntimeError("BridgeEngine is already running")
        stack = AsyncExitStack()
        try:
            task_group = await stack.enter_async_context(anyio.create_task_group())
        except BaseException:
            await stack.aclose()
            raise
        self._lifecycle_stack = stack
        self._worker_task_group = task_group
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    @asynccontextmanager
    async def lifecycle(self) -> AsyncIterator[BridgeEngine]:
        async with self:
            yield self

    async def open_session(
        self,
        *,
        session_key: str,
        plan: EndpointPlan,
        observer: BridgeObserver,
    ) -> BridgeSession:
        worker_task_group = self._require_worker_task_group()
        if session_key in self._session_keys:
            raise ValueError(f"Bridge session is already open: {session_key}")
        router = self._create_router(plan, observer, session_key, worker_task_group)
        session = BridgeSession(session_key, plan, router, self._remove_session)
        await router.start()
        self._sessions.append(session)
        self._session_keys.add(session_key)
        return session

    async def aclose(self) -> None:
        stack = self._lifecycle_stack
        if stack is None:
            return
        for session in reversed(self._sessions.copy()):
            await session.aclose()
        self._worker_task_group = None
        self._lifecycle_stack = None
        await stack.aclose()

    def _create_router(
        self,
        plan: EndpointPlan,
        observer: BridgeObserver,
        session_key: str,
        worker_task_group: TaskGroup,
    ) -> McpSessionRouter:
        if plan.mode is EndpointMode.AGGREGATE:
            return AggregateRouter(
                plan,
                observer,
                session_key,
                self._create_runtime,
                worker_task_group,
                version=self._version,
            )
        return PassthroughRouter(
            self._create_runtime(plan.bindings[0]),
            observer,
            session_key,
            worker_task_group,
        )

    def _create_runtime(self, binding: BindingPlan) -> UpstreamRuntime:
        return UpstreamRuntime(
            binding.upstream,
            name=binding.upstream_name,
            version=self._version,
            upstream_client=self._client_factory.create(binding.upstream),
        )

    def _remove_session(self, session: BridgeSession) -> None:
        if session in self._sessions:
            self._sessions.remove(session)
        self._session_keys.discard(session.session_key)

    def _require_worker_task_group(self) -> TaskGroup:
        if self._worker_task_group is None:
            raise RuntimeError("BridgeEngine is not running")
        return self._worker_task_group
