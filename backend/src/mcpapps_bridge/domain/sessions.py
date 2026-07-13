"""Domain records for downstream bridge sessions and upstream connections."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from .topology import DomainModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BridgeSessionStatus(StrEnum):
    STARTING = "starting"
    ACTIVE = "active"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


class UpstreamSessionStatus(StrEnum):
    CONNECTING = "connecting"
    ACTIVE = "active"
    CLOSED = "closed"
    FAILED = "failed"


class BridgeSessionRecord(DomainModel):
    session_id: UUID = Field(default_factory=uuid4)
    endpoint_id: UUID
    downstream_transport_session_id: str | None = None
    status: BridgeSessionStatus = BridgeSessionStatus.STARTING
    created_at: datetime = Field(default_factory=utc_now)
    last_activity_at: datetime = Field(default_factory=utc_now)
    closed_at: datetime | None = None
    error_message: str | None = None


class UpstreamSessionRecord(DomainModel):
    upstream_session_id: UUID = Field(default_factory=uuid4)
    bridge_session_id: UUID
    upstream_server_id: UUID
    status: UpstreamSessionStatus = UpstreamSessionStatus.CONNECTING
    connected_at: datetime | None = None
    closed_at: datetime | None = None
    error_message: str | None = None
