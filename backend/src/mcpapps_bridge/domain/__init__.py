"""Public domain contracts for managed bridge topology and sessions."""

from .sessions import (
    BridgeSessionRecord,
    BridgeSessionStatus,
    UpstreamSessionRecord,
    UpstreamSessionStatus,
)
from .topology import (
    EndpointBinding,
    EndpointDefinition,
    EndpointMode,
    EndpointSessionPolicy,
    SseConnection,
    StdioConnection,
    StreamableHttpConnection,
    UpstreamConnection,
    UpstreamServerDefinition,
    UpstreamSessionMode,
)

__all__ = [
    "BridgeSessionRecord",
    "BridgeSessionStatus",
    "EndpointBinding",
    "EndpointDefinition",
    "EndpointMode",
    "EndpointSessionPolicy",
    "SseConnection",
    "StdioConnection",
    "StreamableHttpConnection",
    "UpstreamConnection",
    "UpstreamServerDefinition",
    "UpstreamSessionMode",
    "UpstreamSessionRecord",
    "UpstreamSessionStatus",
]
