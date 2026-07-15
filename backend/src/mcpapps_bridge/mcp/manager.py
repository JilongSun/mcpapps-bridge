"""Managed passthrough endpoints and isolated bridge session runtimes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import anyio
from anyio.abc import TaskGroup, TaskStatus

from mcpapps_bridge.domain import (
    BridgeSessionRecord,
    BridgeSessionStatus,
    EndpointDefinition,
    EndpointMode,
    SseConnection,
    StdioConnection,
    StreamableHttpConnection,
    UpstreamServerDefinition,
)
from mcpapps_bridge.repositories import (
    BridgeSessionRepository,
    EndpointRepository,
    UpstreamServerRepository,
)
from mcpapps_bridge.session import BridgeSessionStore, BridgeSessionStoreFactory

from .downstream import BridgeDownstreamServer
from .handlers import ProxyHandlers
from .runtime import UpstreamRuntime
from .upstream import (
    DefaultUpstreamMcpClientFactory,
    UpstreamMcpClientFactory,
    UpstreamServerConfig,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class PublishedEndpoint:
    definition: EndpointDefinition
    upstream_server: UpstreamServerDefinition

    @property
    def path(self) -> str:
        return self.definition.path


@dataclass(frozen=True)
class PassthroughSessionRuntime:
    session_id: UUID
    endpoint_id: UUID
    runtime: UpstreamRuntime
    downstream: BridgeDownstreamServer
    stop_event: anyio.Event
    closed_event: anyio.Event


class BridgeManager:
    """Owns managed endpoints and one isolated runtime per downstream session."""

    def __init__(
        self,
        upstream_servers: UpstreamServerRepository,
        endpoints: EndpointRepository,
        sessions: BridgeSessionRepository,
        session_store_factory: BridgeSessionStoreFactory,
        *,
        upstream_client_factory: UpstreamMcpClientFactory | None = None,
        version: str = "0.1.0",
    ) -> None:
        self._upstream_servers = upstream_servers
        self._endpoints = endpoints
        self._sessions = sessions
        self._session_store_factory = session_store_factory
        self._upstream_client_factory = upstream_client_factory or DefaultUpstreamMcpClientFactory()
        self._version = version
        self._published: dict[UUID, PublishedEndpoint] = {}
        self._slug_index: dict[str, UUID] = {}
        self._active_sessions: dict[UUID, PassthroughSessionRuntime] = {}
        self._lifecycle_stack: AsyncExitStack | None = None
        self._task_group: TaskGroup | None = None
        self._started = False

    @property
    def published_endpoints(self) -> list[PublishedEndpoint]:
        return list(self._published.values())

    @property
    def default_endpoint(self) -> PublishedEndpoint:
        try:
            return next(iter(self._published.values()))
        except StopIteration:
            raise RuntimeError("BridgeManager has no published endpoints") from None

    async def add_upstream_server(self, server: UpstreamServerDefinition) -> None:
        await self._upstream_servers.add(server)

    async def add_endpoint(self, endpoint: EndpointDefinition) -> PublishedEndpoint:
        published = await self._build_published_endpoint(endpoint)
        await self._endpoints.add(endpoint)
        self._register_published_endpoint(published)
        return published

    async def load_published_endpoints(self) -> None:
        self._published.clear()
        self._slug_index.clear()
        for endpoint in await self._endpoints.list():
            if endpoint.enabled:
                self._register_published_endpoint(await self._build_published_endpoint(endpoint))

    async def _build_published_endpoint(
        self,
        endpoint: EndpointDefinition,
    ) -> PublishedEndpoint:
        if not endpoint.enabled:
            raise ValueError(f"Cannot publish disabled endpoint: {endpoint.slug}")
        if endpoint.mode is not EndpointMode.PASSTHROUGH:
            raise NotImplementedError("Aggregate endpoints are not implemented")

        binding = next(binding for binding in endpoint.bindings if binding.enabled)
        server = await self._upstream_servers.get(binding.upstream_server_id)
        if server is None:
            raise ValueError(f"Unknown upstream server: {binding.upstream_server_id}")
        if not server.enabled:
            raise ValueError(f"Cannot bind disabled upstream server: {server.slug}")

        return PublishedEndpoint(definition=endpoint, upstream_server=server)

    def _register_published_endpoint(self, published: PublishedEndpoint) -> None:
        endpoint = published.definition
        self._published[endpoint.endpoint_id] = published
        self._slug_index[endpoint.slug] = endpoint.endpoint_id

    def resolve_published_endpoint(self, slug: str) -> PublishedEndpoint | None:
        endpoint_id = self._slug_index.get(slug)
        return self._published.get(endpoint_id) if endpoint_id is not None else None

    async def open_passthrough_session(self, endpoint_slug: str) -> PassthroughSessionRuntime:
        task_group = self._require_task_group()
        endpoint = self.resolve_published_endpoint(endpoint_slug)
        if endpoint is None:
            raise KeyError(f"Unknown endpoint: {endpoint_slug}")

        session = await self._create_session_record(endpoint.definition.endpoint_id)
        store = await self.get_session_store(session.session_id)
        runtime = self._create_upstream_runtime(endpoint, store)
        handlers = ProxyHandlers(runtime, store)
        downstream = BridgeDownstreamServer(
            handlers,
            identity_provider=lambda: runtime.identity,
            name=endpoint.definition.display_name,
            version=self._version,
        )
        active = PassthroughSessionRuntime(
            session_id=session.session_id,
            endpoint_id=endpoint.definition.endpoint_id,
            runtime=runtime,
            downstream=downstream,
            stop_event=anyio.Event(),
            closed_event=anyio.Event(),
        )
        return await task_group.start(self._run_passthrough_session, active)

    async def resolve_passthrough_session(
        self,
        endpoint_slug: str,
        transport_session_id: str,
    ) -> PassthroughSessionRuntime | None:
        endpoint = self.resolve_published_endpoint(endpoint_slug)
        if endpoint is None:
            return None
        session = await self._sessions.get_by_transport_session_id(transport_session_id)
        if session is None or session.endpoint_id != endpoint.definition.endpoint_id:
            return None
        active = self._active_sessions.get(session.session_id)
        if active is not None:
            await self.touch_session(active.session_id)
        return active

    async def bind_transport_session(
        self,
        active: PassthroughSessionRuntime,
        transport_session_id: str,
    ) -> BridgeSessionRecord:
        session = await self._require_session(active.session_id)
        if session.downstream_transport_session_id not in {None, transport_session_id}:
            raise ValueError(f"Bridge session is already bound: {active.session_id}")
        updated = session.model_copy(
            update={
                "downstream_transport_session_id": transport_session_id,
                "last_activity_at": utc_now(),
            }
        )
        await self._sessions.update(updated)
        return updated.model_copy(deep=True)

    async def close_passthrough_session(self, active: PassthroughSessionRuntime) -> None:
        session = await self._sessions.get(active.session_id)
        if session is None or session.status is BridgeSessionStatus.CLOSED:
            return
        await self._set_session_status(active.session_id, BridgeSessionStatus.CLOSING)
        active.stop_event.set()
        await active.closed_event.wait()

    async def get_session(self, session_id: UUID) -> BridgeSessionRecord | None:
        return await self._sessions.get(session_id)

    async def list_sessions(self, endpoint_id: UUID | None = None) -> list[BridgeSessionRecord]:
        return await self._sessions.list(endpoint_id)

    async def get_session_store(self, session_id: UUID) -> BridgeSessionStore:
        store = await self._session_store_factory.get(session_id)
        if store is None:
            raise KeyError(f"No session store for bridge session: {session_id}")
        return store

    async def touch_session(self, session_id: UUID) -> BridgeSessionRecord:
        session = await self._require_session(session_id)
        updated = session.model_copy(update={"last_activity_at": utc_now()})
        await self._sessions.update(updated)
        return updated.model_copy(deep=True)

    @asynccontextmanager
    async def lifecycle(self) -> AsyncIterator[None]:
        await self.start()
        try:
            yield
        finally:
            await self.close()

    async def start(self) -> None:
        if self._started:
            return
        stack = AsyncExitStack()
        try:
            task_group = await stack.enter_async_context(anyio.create_task_group())
        except Exception:
            await stack.aclose()
            raise
        self._lifecycle_stack = stack
        self._task_group = task_group
        self._started = True

    async def close(self) -> None:
        if not self._started:
            return
        active_sessions = list(self._active_sessions.values())
        for active in active_sessions:
            session = await self._sessions.get(active.session_id)
            if session is not None and session.status is not BridgeSessionStatus.CLOSED:
                await self._set_session_status(active.session_id, BridgeSessionStatus.CLOSING)
            active.stop_event.set()
        for active in active_sessions:
            await active.closed_event.wait()

        stack = self._lifecycle_stack
        self._started = False
        self._task_group = None
        self._lifecycle_stack = None
        if stack is not None:
            await stack.aclose()

    async def _create_session_record(self, endpoint_id: UUID) -> BridgeSessionRecord:
        endpoint = await self._endpoints.get(endpoint_id)
        if endpoint is None:
            raise KeyError(f"Unknown endpoint: {endpoint_id}")
        if not endpoint.enabled:
            raise ValueError(f"Cannot create a session for disabled endpoint: {endpoint.slug}")

        session = BridgeSessionRecord(endpoint_id=endpoint_id)
        await self._session_store_factory.create(session.session_id)
        try:
            await self._sessions.add(session)
        except Exception:
            await self._session_store_factory.remove(session.session_id)
            raise
        return session.model_copy(deep=True)

    async def _run_passthrough_session(
        self,
        active: PassthroughSessionRuntime,
        *,
        task_status: TaskStatus[PassthroughSessionRuntime] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        ready = False
        failed = False
        try:
            await active.runtime.start()
            async with active.downstream.run_http_transports():
                self._active_sessions[active.session_id] = active
                await self._set_session_status(active.session_id, BridgeSessionStatus.ACTIVE)
                ready = True
                task_status.started(active)
                await active.stop_event.wait()
        except Exception as exc:
            failed = True
            await self._set_session_status(
                active.session_id,
                BridgeSessionStatus.FAILED,
                error_message=str(exc),
            )
            if not ready:
                raise
        finally:
            self._active_sessions.pop(active.session_id, None)
            with anyio.CancelScope(shield=True):
                try:
                    await active.runtime.close()
                    if not failed:
                        await self._set_session_status(
                            active.session_id,
                            BridgeSessionStatus.CLOSED,
                            closed_at=utc_now(),
                        )
                finally:
                    active.closed_event.set()

    def _create_upstream_runtime(
        self,
        endpoint: PublishedEndpoint,
        store: BridgeSessionStore,
    ) -> UpstreamRuntime:
        config = self._to_upstream_config(endpoint.upstream_server)
        return UpstreamRuntime(
            config,
            store,
            name=endpoint.upstream_server.display_name,
            version=self._version,
            upstream_client=self._upstream_client_factory.create(config),
        )

    def _require_task_group(self) -> TaskGroup:
        if self._task_group is None:
            raise RuntimeError("BridgeManager is not running")
        return self._task_group

    async def _require_session(self, session_id: UUID) -> BridgeSessionRecord:
        session = await self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Unknown bridge session: {session_id}")
        return session

    async def _set_session_status(
        self,
        session_id: UUID,
        status: BridgeSessionStatus,
        *,
        error_message: str | None = None,
        closed_at: datetime | None = None,
    ) -> None:
        session = await self._require_session(session_id)
        updated = session.model_copy(
            update={
                "status": status,
                "last_activity_at": utc_now(),
                "error_message": error_message,
                "closed_at": closed_at,
            }
        )
        await self._sessions.update(updated)

    def _to_upstream_config(self, server: UpstreamServerDefinition) -> UpstreamServerConfig:
        connection = server.connection
        if isinstance(connection, StreamableHttpConnection):
            return UpstreamServerConfig(
                transport=connection.transport,
                url=str(connection.url),
                headers=connection.headers,
                httpx_timeout_seconds=connection.timeout_seconds,
            )
        if isinstance(connection, SseConnection):
            return UpstreamServerConfig(
                transport=connection.transport,
                url=str(connection.url),
                headers=connection.headers,
            )
        if isinstance(connection, StdioConnection):
            return UpstreamServerConfig(
                transport=connection.transport,
                command=connection.command,
                args=connection.args,
                cwd=connection.cwd,
                env=connection.env,
            )
        raise TypeError(f"Unsupported upstream connection: {type(connection).__name__}")
