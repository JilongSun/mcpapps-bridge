"""Durable Agent Session bindings and unresolved Target execution ownership, not transcripts."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AgentSessionRow(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (
        UniqueConstraint(
            "runtime_binding_id", "remote_session_id", name="uq_agent_session_remote_binding"
        ),
        Index("ix_agent_sessions_target_created", "target_id", "created_at"),
    )

    session_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    target_id: Mapped[str] = mapped_column(String(255))
    runtime_binding_id: Mapped[str] = mapped_column(String(255))
    remote_session_id: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UnsettledAgentRunRow(Base):
    __tablename__ = "unsettled_agent_runs"

    target_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_sessions.session_id", ondelete="RESTRICT")
    )
    run_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    runtime_binding_id: Mapped[str] = mapped_column(String(255))
    remote_run_id: Mapped[str | None] = mapped_column(Text)
