"""Session store factory port."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .protocol import BridgeSessionStore


class BridgeSessionStoreFactory(Protocol):
    async def create(self, session_id: UUID) -> BridgeSessionStore: ...

    async def get(self, session_id: UUID) -> BridgeSessionStore | None: ...

    async def remove(self, session_id: UUID) -> None: ...
