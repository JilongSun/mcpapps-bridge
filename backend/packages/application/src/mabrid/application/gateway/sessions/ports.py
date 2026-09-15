"""Persistence port required by Gateway session lifecycle use cases."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .models import BridgeSessionRecord
from .queries import SessionPage, SessionPageRequest


class BridgeSessionRepository(Protocol):
    async def add(self, session: BridgeSessionRecord) -> None: ...

    async def update(self, session: BridgeSessionRecord) -> None: ...

    async def get(self, session_id: UUID) -> BridgeSessionRecord | None: ...

    async def list(self, endpoint_id: UUID | None = None) -> list[BridgeSessionRecord]: ...


class SessionHistoryReader(Protocol):
    async def list_sessions(self, request: SessionPageRequest) -> SessionPage: ...

    async def get_session(self, session_id: UUID) -> BridgeSessionRecord | None: ...
