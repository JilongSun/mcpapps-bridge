"""SQLite rows for bridge session lifecycle and inspection projections.

Transport correlation is process-local because MCP SDK transport state cannot survive restart.
Inspection events and snapshots are stored as application-owned JSON contracts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from .base import Base


class BridgeSessionRow(Base):
    __tablename__ = "bridge_sessions"
    __table_args__ = (
        Index("ix_bridge_sessions_endpoint_status_created", "endpoint_id", "status", "created_at"),
    )

    session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    endpoint_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("endpoints.endpoint_id", ondelete="RESTRICT"),
        nullable=False,
    )
    endpoint_revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("endpoint_revisions.revision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)


class SessionEventRow(Base):
    __tablename__ = "session_events"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_session_events_session_sequence"),
        Index("ix_session_events_session_sequence", "session_id", "sequence"),
    )

    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("bridge_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SessionSnapshotRow(Base):
    __tablename__ = "session_snapshots"

    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("bridge_sessions.session_id", ondelete="CASCADE"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
