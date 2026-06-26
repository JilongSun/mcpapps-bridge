"""Typed bridge events emitted by the backend session runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, TypeAlias
from uuid import uuid4

from pydantic import BaseModel, Field

from mcpapps_bridge.models import (
    AppResource,
    ToolCallRecord,
    ToolDescriptor,
    UpstreamInitialization,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def next_event_id() -> str:
    return str(uuid4())


class BaseSessionEvent(BaseModel):
    event_id: str = Field(default_factory=next_event_id)
    session_id: str
    created_at: datetime = Field(default_factory=utc_now)


class SessionStartedEvent(BaseSessionEvent):
    kind: Literal["session.started"] = "session.started"
    upstream: UpstreamInitialization | None = None


class ToolDiscoveredEvent(BaseSessionEvent):
    kind: Literal["tool.discovered"] = "tool.discovered"
    tool: ToolDescriptor


class ToolCallStartedEvent(BaseSessionEvent):
    kind: Literal["tool.call.started"] = "tool.call.started"
    call: ToolCallRecord


class ToolCallCompletedEvent(BaseSessionEvent):
    kind: Literal["tool.call.completed"] = "tool.call.completed"
    call: ToolCallRecord


class AppResourceLoadedEvent(BaseSessionEvent):
    kind: Literal["app.resource.loaded"] = "app.resource.loaded"
    resource: AppResource


class ErrorRaisedEvent(BaseSessionEvent):
    kind: Literal["error.raised"] = "error.raised"
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


SessionEvent: TypeAlias = (
    SessionStartedEvent
    | ToolDiscoveredEvent
    | ToolCallStartedEvent
    | ToolCallCompletedEvent
    | AppResourceLoadedEvent
    | ErrorRaisedEvent
)
