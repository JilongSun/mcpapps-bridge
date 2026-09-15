"""Read contracts for persisted session snapshots and sequenced event history."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from .events import SessionEvent


class InspectionQueryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SessionEventPageRequest(InspectionQueryModel):
    session_id: UUID
    after: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)


class SequencedSessionEvent(InspectionQueryModel):
    sequence: PositiveInt
    event: SessionEvent


class SessionEventPage(InspectionQueryModel):
    items: tuple[SequencedSessionEvent, ...]
    next_after: int | None = Field(default=None, ge=1)
