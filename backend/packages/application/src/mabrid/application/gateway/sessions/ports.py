"""Persistence port required by Gateway session lifecycle use cases."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .models import BridgeSessionRecord


class BridgeSessionRepository(Protocol):
    async def add(self, session: BridgeSessionRecord) -> None: ...

    async def update(self, session: BridgeSessionRecord) -> None: ...

    async def get(self, session_id: UUID) -> BridgeSessionRecord | None: ...

    async def list(self, endpoint_id: UUID | None = None) -> list[BridgeSessionRecord]: ...
