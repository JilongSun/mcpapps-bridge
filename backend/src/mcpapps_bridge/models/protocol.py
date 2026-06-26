"""Typed protocol and session models for the bridge runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SessionStatus(StrEnum):
    STARTING = "starting"
    READY = "ready"
    ERROR = "error"
    CLOSED = "closed"


class ToolCallStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class UpstreamInitialization(BaseModel):
    server_name: str
    server_version: str | None = None
    protocol_version: str | None = None
    instructions: str | None = None
    supports_tools: bool = True
    supports_resources: bool = False
    raw_capabilities: dict[str, Any] = Field(default_factory=dict)


class ToolDescriptor(BaseModel):
    name: str
    title: str | None = None
    description: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    annotations: dict[str, Any] = Field(default_factory=dict)
    ui_resource_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCallResult(BaseModel):
    content: list[dict[str, Any]] = Field(default_factory=list)
    structured_content: dict[str, Any] | None = None
    is_error: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCallRecord(BaseModel):
    call_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: ToolCallStatus
    result: ToolCallResult | None = None
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class AppResource(BaseModel):
    uri: str
    mime_type: str
    text: str | None = None
    blob: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    loaded_at: datetime = Field(default_factory=utc_now)


class ResourceDescriptor(BaseModel):
    name: str
    uri: str
    title: str | None = None
    description: str | None = None
    mime_type: str | None = None
    annotations: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    size: int | None = None


class BridgeSessionSnapshot(BaseModel):
    session_id: str
    status: SessionStatus = SessionStatus.STARTING
    upstream: UpstreamInitialization | None = None
    discovered_tools: list[ToolDescriptor] = Field(default_factory=list)
    active_tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    loaded_resources: list[AppResource] = Field(default_factory=list)
    last_error: str | None = None
    event_count: int = 0
    updated_at: datetime = Field(default_factory=utc_now)
