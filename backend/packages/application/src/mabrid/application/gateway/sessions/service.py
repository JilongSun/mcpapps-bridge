"""Published endpoints and isolated bridge session lifecycle coordination.

The coordinator owns live core sessions and process-local transport correlation. Persistence
stores application lifecycle history, never MCP SDK transport state that cannot survive restart.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import anyio
from anyio.abc import TaskGroup, TaskStatus
from mabrid.bridge import (
    BridgeEngine,
    BridgeSession,
    UpstreamClientFactory,
)

from ..inspection.ports import BridgeSessionStore, BridgeSessionStoreFactory
from ..inspection.projector import SessionInspectionProjector
from ..topology.ports import TopologyReader
from ..topology.revisions import EndpointTopologyRevision
from .models import BridgeSessionRecord, BridgeSessionStatus
from .ports import BridgeSessionRepository
from .publication import PublishedEndpoint, PublishedTopology

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class BridgeSessionRuntime:
    session_id: UUID
    endpoint_id: UUID
    bridge_session: BridgeSession
    stop_event: anyio.Event
    closed_event: anyio.Event


class GatewaySessionCoordinator:
    """Coordinates managed topology, persisted sessions, and core bridge lifecycles."""

    def __init__(
        self,
        topology: TopologyReader,
        sessions: BridgeSessionRepository,
        session_store_factory: BridgeSessionStoreFactory,
        *,
        upstream_client_factory: UpstreamClientFactory | None = None,
        version: str = "0.1.0",
    ) -> None:
        self._published_topology = PublishedTopology(topology)
        self._sessions = sessions
        self._session_store_factory = session_store_factory
        self._version = version
        self._engine = BridgeEngine(
            client_factory=upstream_client_factory,
            version=version,
        )
        self._active_sessions: dict[UUID, BridgeSessionRuntime] = {}
        self._transport_sessions: dict[str, UUID] = {}
        self._session_transport_ids: dict[UUID, str] = {}
        self._lifecycle_stack: AsyncExitStack | None = None
        self._task_group: TaskGroup | None = None
        self._started = False

    @property
    def published_endpoints(self) -> list[PublishedEndpoint]:
        return self._published_topology.endpoints

    async def load_published_endpoints(self) -> None:
        await self._published_topology.load()

    def resolve_published_endpoint(self, slug: str) -> PublishedEndpoint | None:
        return self._published_topology.resolve(slug)

    async def open_session(self, endpoint_slug: str) -> BridgeSessionRuntime:
        task_group = self._require_task_group()
        endpoint = self.resolve_published_endpoint(endpoint_slug)
        if endpoint is None:
            raise KeyError(f"Unknown endpoint: {endpoint_slug}")

        session = await self._create_session_record(endpoint.revision)
        logger.info(
            "Bridge session created: session_id=%s endpoint=%s",
            session.session_id,
            endpoint_slug,
        )
        store = await self._get_session_store(session.session_id)
        session_key = str(session.session_id)
        observer = SessionInspectionProjector(session_key, endpoint.revision, store)
        try:
            bridge_session = await self._engine.open_session(
                session_key=session_key,
                plan=endpoint.plan,
                observer=observer,
            )
        except Exception as exc:
            await self._set_session_status(
                session.session_id,
                BridgeSessionStatus.FAILED,
                error_message=str(exc),
            )
            raise
        downstream_identity = bridge_session.identity
        logger.info(
            "Downstream host identity: server_name=%s server_version=%s "
            "tools=%s resources=%s protocol=%s",
            downstream_identity.server_name,
            downstream_identity.server_version,
            downstream_identity.supports_tools,
            downstream_identity.supports_resources,
            downstream_identity.protocol_version,
        )
        active = BridgeSessionRuntime(
            session_id=session.session_id,
            endpoint_id=endpoint.revision.endpoint_id,
            bridge_session=bridge_session,
            stop_event=anyio.Event(),
            closed_event=anyio.Event(),
        )
        return await task_group.start(self._run_session, active)

    async def resolve_session(
        self,
        endpoint_slug: str,
        transport_session_id: str,
    ) -> BridgeSessionRuntime | None:
        endpoint = self.resolve_published_endpoint(endpoint_slug)
        if endpoint is None:
            return None
        session_id = self._transport_sessions.get(transport_session_id)
        if session_id is None:
            return None
        active = self._active_sessions.get(session_id)
        if active is None or active.endpoint_id != endpoint.revision.endpoint_id:
            return None
        await self._touch_session(active.session_id)
        return active

    async def bind_transport_session(
        self,
        active: BridgeSessionRuntime,
        transport_session_id: str,
    ) -> None:
        if self._active_sessions.get(active.session_id) is not active:
            raise ValueError(f"Bridge session is not active: {active.session_id}")
        current_transport_id = self._session_transport_ids.get(active.session_id)
        if current_transport_id not in {None, transport_session_id}:
            raise ValueError(f"Bridge session is already bound: {active.session_id}")
        current_session_id = self._transport_sessions.get(transport_session_id)
        if current_session_id not in {None, active.session_id}:
            raise ValueError(f"Transport session is already bound: {transport_session_id}")
        self._transport_sessions[transport_session_id] = active.session_id
        self._session_transport_ids[active.session_id] = transport_session_id
        await self._touch_session(active.session_id)

    async def close_session(self, active: BridgeSessionRuntime) -> None:
        session = await self._sessions.get(active.session_id)
        if session is None or session.status is BridgeSessionStatus.CLOSED:
            return
        await self._set_session_status(active.session_id, BridgeSessionStatus.CLOSING)
        active.stop_event.set()
        await active.closed_event.wait()

    async def _get_session_store(self, session_id: UUID) -> BridgeSessionStore:
        store = await self._session_store_factory.get(session_id)
        if store is None:
            raise KeyError(f"No session store for bridge session: {session_id}")
        return store

    async def _touch_session(self, session_id: UUID) -> BridgeSessionRecord:
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
            await stack.enter_async_context(self._engine)
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

    async def _create_session_record(
        self,
        revision: EndpointTopologyRevision,
    ) -> BridgeSessionRecord:
        if not revision.enabled:
            raise ValueError(f"Cannot create a session for disabled endpoint: {revision.slug}")
        session = BridgeSessionRecord(
            endpoint_id=revision.endpoint_id,
            endpoint_revision_id=revision.revision_id,
        )
        await self._session_store_factory.create(session.session_id)
        try:
            await self._sessions.add(session)
        except Exception:
            await self._session_store_factory.remove(session.session_id)
            raise
        return session.model_copy(deep=True)

    async def _run_session(
        self,
        active: BridgeSessionRuntime,
        *,
        task_status: TaskStatus[BridgeSessionRuntime] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        ready = False
        failed = False
        try:
            async with active.bridge_session.transport_lifecycle():
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
            transport_session_id = self._session_transport_ids.pop(active.session_id, None)
            if transport_session_id is not None:
                self._transport_sessions.pop(transport_session_id, None)
            with anyio.CancelScope(shield=True):
                try:
                    await active.bridge_session.aclose()
                    if not failed:
                        await self._set_session_status(
                            active.session_id,
                            BridgeSessionStatus.CLOSED,
                            closed_at=utc_now(),
                        )
                finally:
                    active.closed_event.set()

    def _require_task_group(self) -> TaskGroup:
        if self._task_group is None:
            raise RuntimeError("GatewaySessionCoordinator is not running")
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
