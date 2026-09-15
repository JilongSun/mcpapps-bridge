"""Read contracts for paginated bridge session lifecycle history."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import BridgeSessionRecord, BridgeSessionStatus


class SessionQueryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SessionKeyset(SessionQueryModel):
    created_at: datetime
    session_id: UUID

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class SessionPageRequest(SessionQueryModel):
    endpoint_id: UUID | None = None
    status: BridgeSessionStatus | None = None
    before: SessionKeyset | None = None
    limit: int = Field(default=50, ge=1, le=200)


class SessionPage(SessionQueryModel):
    items: tuple[BridgeSessionRecord, ...]
    next_keyset: SessionKeyset | None = None
