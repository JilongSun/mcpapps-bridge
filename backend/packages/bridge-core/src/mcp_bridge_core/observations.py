"""Typed observations emitted by bridge core."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .protocol import AppResource, ToolCallResult, ToolDescriptor, UpstreamIdentity


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ObservationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BridgeFailureCode(StrEnum):
    INVALID_PLAN = "invalid_plan"
    UNKNOWN_TOOL = "unknown_tool"
    UNKNOWN_RESOURCE = "unknown_resource"
    BINDING_UNAVAILABLE = "binding_unavailable"
    UPSTREAM_TRANSPORT = "upstream_transport"
    UPSTREAM_PROTOCOL = "upstream_protocol"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    PROTOCOL_ADAPTER = "protocol_adapter"


class BindingAvailabilityStatus(StrEnum):
    UNKNOWN = "unknown"
    AVAILABLE = "available"
    FAILED = "failed"


class BridgeFailure(ObservationModel):
    code: BridgeFailureCode
    message: str
    retryable: bool = False
    binding_key: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ObservationBase(ObservationModel):
    session_key: str
    observed_at: datetime = Field(default_factory=utc_now)


class BridgeSessionStarted(ObservationBase):
    kind: Literal["bridge.session.started"] = "bridge.session.started"
    identity: UpstreamIdentity


class BindingAvailabilityChanged(ObservationBase):
    kind: Literal["bridge.binding.availability_changed"] = "bridge.binding.availability_changed"
    binding_key: str
    status: BindingAvailabilityStatus
    identity: UpstreamIdentity | None = None
    failure: BridgeFailure | None = None


class ToolsPublished(ObservationBase):
    kind: Literal["bridge.tools.published"] = "bridge.tools.published"
    tools: tuple[ToolDescriptor, ...]


class ToolCallStarted(ObservationBase):
    kind: Literal["bridge.tool_call.started"] = "bridge.tool_call.started"
    operation_key: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallCompleted(ObservationBase):
    kind: Literal["bridge.tool_call.completed"] = "bridge.tool_call.completed"
    operation_key: str
    result: ToolCallResult | None = None
    failure: BridgeFailure | None = None


class ResourceLoaded(ObservationBase):
    kind: Literal["bridge.resource.loaded"] = "bridge.resource.loaded"
    binding_key: str | None = None
    resource: AppResource


class BridgeErrorRaised(ObservationBase):
    kind: Literal["bridge.error.raised"] = "bridge.error.raised"
    operation: str
    failure: BridgeFailure


BridgeObservation = Annotated[
    BridgeSessionStarted
    | BindingAvailabilityChanged
    | ToolsPublished
    | ToolCallStarted
    | ToolCallCompleted
    | ResourceLoaded
    | BridgeErrorRaised,
    Field(discriminator="kind"),
]
