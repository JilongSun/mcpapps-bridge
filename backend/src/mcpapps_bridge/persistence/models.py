"""SQLAlchemy models for managed topology and session history."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import Uuid


class Base(DeclarativeBase):
    pass


class UpstreamServerRow(Base):
    __tablename__ = "upstream_servers"

    server_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    transport: Mapped[str] = mapped_column(String(32), nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    command: Mapped[str | None] = mapped_column(Text)
    args_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    cwd: Mapped[str | None] = mapped_column(Text)
    env_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    headers_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    timeout_seconds: Mapped[float | None] = mapped_column(Float)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    current_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("upstream_revisions.revision_id", ondelete="RESTRICT"),
    )


class UpstreamRevisionRow(Base):
    __tablename__ = "upstream_revisions"
    __table_args__ = (
        UniqueConstraint("server_id", "revision_number", name="uq_upstream_revision_number"),
    )

    revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    server_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("upstream_servers.server_id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    transport: Mapped[str] = mapped_column(String(32), nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    command: Mapped[str | None] = mapped_column(Text)
    args_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    cwd: Mapped[str | None] = mapped_column(Text)
    env_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    headers_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    timeout_seconds: Mapped[float | None] = mapped_column(Float)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EndpointRow(Base):
    __tablename__ = "endpoints"

    endpoint_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    upstream_session_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    lazy_upstream_connections: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    idle_timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    current_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("endpoint_revisions.revision_id", ondelete="RESTRICT"),
    )


class EndpointRevisionRow(Base):
    __tablename__ = "endpoint_revisions"
    __table_args__ = (
        UniqueConstraint("endpoint_id", "revision_number", name="uq_endpoint_revision_number"),
    )

    revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    endpoint_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("endpoints.endpoint_id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    upstream_session_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    lazy_upstream_connections: Mapped[bool] = mapped_column(Boolean, nullable=False)
    idle_timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EndpointBindingRevisionRow(Base):
    __tablename__ = "endpoint_binding_revisions"
    __table_args__ = (
        Index(
            "ix_endpoint_binding_revisions_endpoint_priority",
            "endpoint_revision_id",
            "enabled",
            "priority",
        ),
    )

    binding_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    binding_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    endpoint_revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("endpoint_revisions.revision_id", ondelete="CASCADE"),
        nullable=False,
    )
    upstream_revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("upstream_revisions.revision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    namespace: Mapped[str | None] = mapped_column(String(255))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class EndpointBindingRow(Base):
    __tablename__ = "endpoint_bindings"
    __table_args__ = (
        Index(
            "ix_endpoint_bindings_endpoint_enabled_priority", "endpoint_id", "enabled", "priority"
        ),
    )

    binding_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    endpoint_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("endpoints.endpoint_id", ondelete="CASCADE"),
        nullable=False,
    )
    upstream_server_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("upstream_servers.server_id", ondelete="RESTRICT"),
        nullable=False,
    )
    namespace: Mapped[str | None] = mapped_column(String(255))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


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
    downstream_transport_session_id: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)


class UpstreamSessionRow(Base):
    __tablename__ = "upstream_sessions"
    __table_args__ = (
        UniqueConstraint(
            "bridge_session_id",
            "upstream_server_id",
            name="uq_upstream_sessions_bridge_server",
        ),
    )

    upstream_session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    bridge_session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("bridge_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    upstream_server_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("upstream_servers.server_id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
