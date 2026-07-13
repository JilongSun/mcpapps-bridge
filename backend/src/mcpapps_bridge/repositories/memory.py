"""Concurrency-safe in-memory repository implementations."""

from __future__ import annotations

from uuid import UUID

import anyio

from mcpapps_bridge.domain import (
    BridgeSessionRecord,
    EndpointDefinition,
    UpstreamServerDefinition,
)


class InMemoryUpstreamServerRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, UpstreamServerDefinition] = {}
        self._lock = anyio.Lock()

    async def add(self, server: UpstreamServerDefinition) -> None:
        async with self._lock:
            if server.server_id in self._items:
                raise ValueError(f"Upstream server already exists: {server.server_id}")
            self._items[server.server_id] = server.model_copy(deep=True)

    async def get(self, server_id: UUID) -> UpstreamServerDefinition | None:
        async with self._lock:
            server = self._items.get(server_id)
            return server.model_copy(deep=True) if server is not None else None

    async def list(self) -> list[UpstreamServerDefinition]:
        async with self._lock:
            return [server.model_copy(deep=True) for server in self._items.values()]


class InMemoryEndpointRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, EndpointDefinition] = {}
        self._slug_index: dict[str, UUID] = {}
        self._lock = anyio.Lock()

    async def add(self, endpoint: EndpointDefinition) -> None:
        async with self._lock:
            if endpoint.endpoint_id in self._items:
                raise ValueError(f"Endpoint already exists: {endpoint.endpoint_id}")
            if endpoint.slug in self._slug_index:
                raise ValueError(f"Endpoint slug already exists: {endpoint.slug}")
            self._items[endpoint.endpoint_id] = endpoint.model_copy(deep=True)
            self._slug_index[endpoint.slug] = endpoint.endpoint_id

    async def get(self, endpoint_id: UUID) -> EndpointDefinition | None:
        async with self._lock:
            endpoint = self._items.get(endpoint_id)
            return endpoint.model_copy(deep=True) if endpoint is not None else None

    async def get_by_slug(self, slug: str) -> EndpointDefinition | None:
        async with self._lock:
            endpoint_id = self._slug_index.get(slug)
            endpoint = self._items.get(endpoint_id) if endpoint_id is not None else None
            return endpoint.model_copy(deep=True) if endpoint is not None else None

    async def list(self) -> list[EndpointDefinition]:
        async with self._lock:
            return [endpoint.model_copy(deep=True) for endpoint in self._items.values()]


class InMemoryBridgeSessionRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, BridgeSessionRecord] = {}
        self._transport_index: dict[str, UUID] = {}
        self._lock = anyio.Lock()

    async def add(self, session: BridgeSessionRecord) -> None:
        async with self._lock:
            if session.session_id in self._items:
                raise ValueError(f"Bridge session already exists: {session.session_id}")
            self._validate_transport_session_id(session)
            self._items[session.session_id] = session.model_copy(deep=True)
            self._index_transport_session(session)

    async def update(self, session: BridgeSessionRecord) -> None:
        async with self._lock:
            previous = self._items.get(session.session_id)
            if previous is None:
                raise KeyError(f"Unknown bridge session: {session.session_id}")
            self._validate_transport_session_id(session)
            if previous.downstream_transport_session_id is not None:
                self._transport_index.pop(previous.downstream_transport_session_id, None)
            self._items[session.session_id] = session.model_copy(deep=True)
            self._index_transport_session(session)

    async def get(self, session_id: UUID) -> BridgeSessionRecord | None:
        async with self._lock:
            session = self._items.get(session_id)
            return session.model_copy(deep=True) if session is not None else None

    async def get_by_transport_session_id(
        self, transport_session_id: str
    ) -> BridgeSessionRecord | None:
        async with self._lock:
            session_id = self._transport_index.get(transport_session_id)
            session = self._items.get(session_id) if session_id is not None else None
            return session.model_copy(deep=True) if session is not None else None

    async def list(self, endpoint_id: UUID | None = None) -> list[BridgeSessionRecord]:
        async with self._lock:
            sessions = self._items.values()
            if endpoint_id is not None:
                sessions = [session for session in sessions if session.endpoint_id == endpoint_id]
            return [session.model_copy(deep=True) for session in sessions]

    def _validate_transport_session_id(self, session: BridgeSessionRecord) -> None:
        transport_session_id = session.downstream_transport_session_id
        if transport_session_id is None:
            return
        existing_session_id = self._transport_index.get(transport_session_id)
        if existing_session_id is not None and existing_session_id != session.session_id:
            raise ValueError(f"Transport session already bound: {transport_session_id}")

    def _index_transport_session(self, session: BridgeSessionRecord) -> None:
        if session.downstream_transport_session_id is not None:
            self._transport_index[session.downstream_transport_session_id] = session.session_id
