"""Presentation envelopes for the composed Agent Host and MCP Apps event stream."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, TypeAlias
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from ..agent_host import AgentRunEvent
from ..mcp_apps import WidgetEvent


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class HostEventModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HostEventBase(HostEventModel):
    event_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    sequence: PositiveInt
    created_at: datetime = Field(default_factory=utc_now)


class HostAgentEvent(HostEventBase):
    kind: Literal["host.agent"] = "host.agent"
    event: AgentRunEvent


class HostWidgetEvent(HostEventBase):
    kind: Literal["host.widget"] = "host.widget"
    event: WidgetEvent


HostEvent: TypeAlias = HostAgentEvent | HostWidgetEvent
