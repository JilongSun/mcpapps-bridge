"""Application journal events adapted from bridge-core observations."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Protocol

from mcp_bridge_core import (
    AppResource,
    BindingAvailabilityStatus,
    BindingAvailabilityChanged,
    BridgeErrorRaised,
    BridgeFailure,
    BridgeObservation,
    BridgeObserver,
    BridgeSessionStarted,
    ResourceLoaded,
    ToolCallCompleted,
    ToolCallResult,
    ToolCallStarted,
    ToolDescriptor,
    ToolsPublished,
    UpstreamIdentity,
)
from pydantic import BaseModel, ConfigDict, Field


class JournalEventModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class JournalEventBase(JournalEventModel):
    session_key: str
    occurred_at: datetime


class SessionStartedJournalEvent(JournalEventBase):
    kind: Literal["session.started"] = "session.started"
    identity: UpstreamIdentity


class BindingAvailabilityJournalEvent(JournalEventBase):
    kind: Literal["binding.availability.changed"] = "binding.availability.changed"
    binding_key: str
    status: BindingAvailabilityStatus
    identity: UpstreamIdentity | None = None
    failure: BridgeFailure | None = None


class ToolsPublishedJournalEvent(JournalEventBase):
    kind: Literal["tools.published"] = "tools.published"
    tools: tuple[ToolDescriptor, ...]


class ToolCallStartedJournalEvent(JournalEventBase):
    kind: Literal["tool_call.started"] = "tool_call.started"
    operation_key: str
    tool_name: str
    arguments: dict[str, object] = Field(default_factory=dict)


class ToolCallCompletedJournalEvent(JournalEventBase):
    kind: Literal["tool_call.completed"] = "tool_call.completed"
    operation_key: str
    result: ToolCallResult | None = None
    failure: BridgeFailure | None = None


class ResourceLoadedJournalEvent(JournalEventBase):
    kind: Literal["resource.loaded"] = "resource.loaded"
    binding_key: str | None = None
    resource: AppResource


class ErrorRaisedJournalEvent(JournalEventBase):
    kind: Literal["error.raised"] = "error.raised"
    operation: str
    failure: BridgeFailure


SessionJournalEvent = Annotated[
    SessionStartedJournalEvent
    | BindingAvailabilityJournalEvent
    | ToolsPublishedJournalEvent
    | ToolCallStartedJournalEvent
    | ToolCallCompletedJournalEvent
    | ResourceLoadedJournalEvent
    | ErrorRaisedJournalEvent,
    Field(discriminator="kind"),
]


class SessionJournal(Protocol):
    async def append(self, event: SessionJournalEvent) -> None: ...


class JournalBridgeObserver(BridgeObserver):
    """Translate core observations into application-owned journal events."""

    def __init__(self, session_key: str, journal: SessionJournal) -> None:
        self._session_key = session_key
        self._journal = journal

    async def observe(self, event: BridgeObservation) -> None:
        if event.session_key != self._session_key:
            raise ValueError(
                f"observation session mismatch: {event.session_key} != {self._session_key}"
            )
        await self._journal.append(_to_journal_event(event))


def _to_journal_event(event: BridgeObservation) -> SessionJournalEvent:
    common = {"session_key": event.session_key, "occurred_at": event.observed_at}
    if isinstance(event, BridgeSessionStarted):
        return SessionStartedJournalEvent(**common, identity=event.identity)
    if isinstance(event, BindingAvailabilityChanged):
        return BindingAvailabilityJournalEvent(
            **common,
            binding_key=event.binding_key,
            status=event.status,
            identity=event.identity,
            failure=event.failure,
        )
    if isinstance(event, ToolsPublished):
        return ToolsPublishedJournalEvent(**common, tools=event.tools)
    if isinstance(event, ToolCallStarted):
        return ToolCallStartedJournalEvent(
            **common,
            operation_key=event.operation_key,
            tool_name=event.tool_name,
            arguments=event.arguments,
        )
    if isinstance(event, ToolCallCompleted):
        return ToolCallCompletedJournalEvent(
            **common,
            operation_key=event.operation_key,
            result=event.result,
            failure=event.failure,
        )
    if isinstance(event, ResourceLoaded):
        return ResourceLoadedJournalEvent(
            **common,
            binding_key=event.binding_key,
            resource=event.resource,
        )
    if isinstance(event, BridgeErrorRaised):
        return ErrorRaisedJournalEvent(
            **common,
            operation=event.operation,
            failure=event.failure,
        )
    raise TypeError(f"Unsupported bridge observation: {type(event).__name__}")
