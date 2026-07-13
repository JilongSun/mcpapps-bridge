"""Session store factory ports and in-memory implementation."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

import anyio

from .memory import InMemoryBridgeSessionStore
from .protocol import BridgeSessionStore


class BridgeSessionStoreFactory(Protocol):
    async def create(self, session_id: UUID) -> BridgeSessionStore: ...

    async def get(self, session_id: UUID) -> BridgeSessionStore | None: ...

    async def remove(self, session_id: UUID) -> None: ...


class InMemoryBridgeSessionStoreFactory:
    def __init__(self) -> None:
        self._stores: dict[UUID, BridgeSessionStore] = {}
        self._lock = anyio.Lock()

    async def create(self, session_id: UUID) -> BridgeSessionStore:
        async with self._lock:
            if session_id in self._stores:
                raise ValueError(f"Session store already exists: {session_id}")
            store = InMemoryBridgeSessionStore(str(session_id))
            self._stores[session_id] = store
            return store

    async def get(self, session_id: UUID) -> BridgeSessionStore | None:
        async with self._lock:
            return self._stores.get(session_id)

    async def remove(self, session_id: UUID) -> None:
        async with self._lock:
            self._stores.pop(session_id, None)
