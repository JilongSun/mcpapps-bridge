"""Durable Gateway session inspection contracts and projection.

Inspection owns application event envelopes, snapshots, store ports, and projection from bridge-core
observations. Core protocol values are converted explicitly; SQLAlchemy payload storage remains an
outer adapter in the deployable server.
"""

from .events import (
    ErrorRaisedEvent,
    ResourceReadEvent,
    SessionEvent,
    SessionStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
    ToolDiscoveredEvent,
    UpstreamAvailabilityChangedEvent,
)
from .models import (
    BridgeSessionSnapshot,
    ResourceContent,
    ResourceDescriptor,
    ResourceReadRecord,
    SessionStatus,
    ToolCallRecord,
    ToolCallResult,
    ToolCallStatus,
    ToolDescriptor,
    UpstreamAvailability,
    UpstreamAvailabilityStatus,
    UpstreamInitialization,
)
from .ports import BridgeSessionStore, BridgeSessionStoreFactory
from .projector import SessionInspectionProjector

__all__ = [
    "BridgeSessionSnapshot",
    "BridgeSessionStore",
    "BridgeSessionStoreFactory",
    "ErrorRaisedEvent",
    "ResourceContent",
    "ResourceDescriptor",
    "ResourceReadEvent",
    "ResourceReadRecord",
    "SessionEvent",
    "SessionStartedEvent",
    "SessionInspectionProjector",
    "SessionStatus",
    "ToolCallCompletedEvent",
    "ToolCallRecord",
    "ToolCallResult",
    "ToolCallStartedEvent",
    "ToolCallStatus",
    "ToolDescriptor",
    "ToolDiscoveredEvent",
    "UpstreamAvailability",
    "UpstreamAvailabilityChangedEvent",
    "UpstreamAvailabilityStatus",
    "UpstreamInitialization",
]
