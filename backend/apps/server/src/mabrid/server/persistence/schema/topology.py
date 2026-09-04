"""SQLite rows for managed topology heads and immutable published revisions.

These rows mirror persistence shape, not application behavior. Conversion to Gateway topology
contracts belongs to the topology adapter package.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from .base import Base


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
            "ix_endpoint_bindings_endpoint_enabled_priority",
            "endpoint_id",
            "enabled",
            "priority",
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
