"""Managed MCP endpoint and bridge session orchestration."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

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
from .upstream import UpstreamMcpClient, UpstreamServerConfig


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class PublishedEndpoint:
    definition: EndpointDefinition
    session_id: UUID
    runtime: UpstreamRuntime
    downstream: BridgeDownstreamServer

    @property
    def path(self) -> str:
        return self.definition.path


class BridgeManager:
    """Owns managed topology, bridge sessions, endpoint runtimes, and lifecycle."""

    def __init__(
        self,
        upstream_servers: UpstreamServerRepository,
        endpoints: EndpointRepository,
        sessions: BridgeSessionRepository,
        session_store_factory: BridgeSessionStoreFactory,
        *,
        version: str = "0.1.0",
    ) -> None:
        self._upstream_servers = upstream_servers
        self._endpoints = endpoints
        self._sessions = sessions
        self._session_store_factory = session_store_factory
        self._version = version
        self._published: dict[UUID, PublishedEndpoint] = {}
        self._slug_index: dict[str, UUID] = {}
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

    async def add_endpoint(
        self,
        endpoint: EndpointDefinition,
        *,
        upstream_client: UpstreamMcpClient | None = None,
    ) -> PublishedEndpoint:
        if self._started:
            raise RuntimeError("Dynamic endpoint publication is not implemented yet")
        if not endpoint.enabled:
            raise ValueError(f"Cannot publish disabled endpoint: {endpoint.slug}")
        if endpoint.mode is not EndpointMode.PASSTHROUGH:
            raise NotImplementedError("Aggregate endpoint runtime is not implemented yet")

        await self._endpoints.add(endpoint)
        binding = next(binding for binding in endpoint.bindings if binding.enabled)
        server = await self._upstream_servers.get(binding.upstream_server_id)
        if server is None:
            raise ValueError(f"Unknown upstream server: {binding.upstream_server_id}")
        if not server.enabled:
            raise ValueError(f"Cannot bind disabled upstream server: {server.slug}")

        session = await self.create_session(endpoint.endpoint_id)
        session_store = await self.get_session_store(session.session_id)
        runtime = UpstreamRuntime(
            self._to_upstream_config(server),
            session_store,
            name=server.display_name,
            version=self._version,
            upstream_client=upstream_client,
        )
        handlers = ProxyHandlers(runtime, session_store)
        downstream = BridgeDownstreamServer(
            handlers,
            identity_provider=lambda: runtime.identity,
            name=endpoint.display_name,
            version=self._version,
        )
        published = PublishedEndpoint(
            definition=endpoint,
            session_id=session.session_id,
            runtime=runtime,
            downstream=downstream,
        )
        self._published[endpoint.endpoint_id] = published
        self._slug_index[endpoint.slug] = endpoint.endpoint_id
        return published

    async def create_session(
        self,
        endpoint_id: UUID,
        *,
        transport_session_id: str | None = None,
    ) -> BridgeSessionRecord:
        endpoint = await self._endpoints.get(endpoint_id)
        if endpoint is None:
            raise KeyError(f"Unknown endpoint: {endpoint_id}")
        if not endpoint.enabled:
            raise ValueError(f"Cannot create a session for disabled endpoint: {endpoint.slug}")

        session = BridgeSessionRecord(
            endpoint_id=endpoint_id,
            downstream_transport_session_id=transport_session_id,
        )
        await self._session_store_factory.create(session.session_id)
        try:
            await self._sessions.add(session)
        except Exception:
            await self._session_store_factory.remove(session.session_id)
            raise
        return session.model_copy(deep=True)

    async def get_session(self, session_id: UUID) -> BridgeSessionRecord | None:
        return await self._sessions.get(session_id)

    async def list_sessions(self, endpoint_id: UUID | None = None) -> list[BridgeSessionRecord]:
        return await self._sessions.list(endpoint_id)

    async def get_session_store(self, session_id: UUID) -> BridgeSessionStore:
        store = await self._session_store_factory.get(session_id)
        if store is None:
            raise KeyError(f"No session store for bridge session: {session_id}")
        return store

    async def bind_transport_session(
        self,
        session_id: UUID,
        transport_session_id: str,
    ) -> BridgeSessionRecord:
        session = await self._require_session(session_id)
        updated = session.model_copy(
            update={
                "downstream_transport_session_id": transport_session_id,
                "last_activity_at": utc_now(),
            }
        )
        await self._sessions.update(updated)
        return updated.model_copy(deep=True)

    async def resolve_transport_session(
        self, transport_session_id: str
    ) -> BridgeSessionRecord | None:
        return await self._sessions.get_by_transport_session_id(transport_session_id)

    async def touch_session(self, session_id: UUID) -> BridgeSessionRecord:
        session = await self._require_session(session_id)
        updated = session.model_copy(update={"last_activity_at": utc_now()})
        await self._sessions.update(updated)
        return updated.model_copy(deep=True)

    async def close_session(self, session_id: UUID) -> BridgeSessionRecord:
        session = await self._require_session(session_id)
        now = utc_now()
        updated = session.model_copy(
            update={
                "status": BridgeSessionStatus.CLOSED,
                "closed_at": now,
                "last_activity_at": now,
            }
        )
        await self._sessions.update(updated)
        return updated.model_copy(deep=True)

    def resolve_published_endpoint(self, slug: str) -> PublishedEndpoint | None:
        endpoint_id = self._slug_index.get(slug)
        return self._published.get(endpoint_id) if endpoint_id is not None else None

    @asynccontextmanager
    async def lifecycle(self) -> AsyncIterator[None]:
        await self.start()
        try:
            async with self.run_http_transports():
                yield
        finally:
            await self.close()

    async def start(self) -> None:
        if self._started:
            return
        started: list[PublishedEndpoint] = []
        failed_endpoint: PublishedEndpoint | None = None
        try:
            for endpoint in self._published.values():
                failed_endpoint = endpoint
                await endpoint.runtime.start()
                await self._set_session_status(endpoint.session_id, BridgeSessionStatus.ACTIVE)
                started.append(endpoint)
        except Exception as exc:
            for endpoint in reversed(started):
                await endpoint.runtime.close()
                await self._set_session_status(endpoint.session_id, BridgeSessionStatus.CLOSED)
            if failed_endpoint is not None:
                await self._set_session_status(
                    failed_endpoint.session_id,
                    BridgeSessionStatus.FAILED,
                    error_message=str(exc),
                )
            raise
        self._started = True

    async def close(self) -> None:
        if not self._started:
            return
        self._started = False
        for endpoint in reversed(self.published_endpoints):
            await self._set_session_status(endpoint.session_id, BridgeSessionStatus.CLOSING)
            await endpoint.runtime.close()
            await self.close_session(endpoint.session_id)

    @asynccontextmanager
    async def run_http_transports(self) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            for endpoint in self._published.values():
                await stack.enter_async_context(endpoint.downstream.run_http_transports())
            yield

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
    ) -> None:
        session = await self._require_session(session_id)
        updated = session.model_copy(
            update={
                "status": status,
                "last_activity_at": utc_now(),
                "error_message": error_message,
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
