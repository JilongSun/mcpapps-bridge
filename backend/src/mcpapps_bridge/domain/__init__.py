"""Public domain contracts for managed bridge topology and sessions."""

from .revisions import EndpointBindingRevision, EndpointTopologyRevision, UpstreamRevision
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
    "EndpointBindingRevision",
    "EndpointDefinition",
    "EndpointMode",
    "EndpointSessionPolicy",
    "EndpointTopologyRevision",
    "SseConnection",
    "StdioConnection",
    "StreamableHttpConnection",
    "UpstreamConnection",
    "UpstreamRevision",
    "UpstreamServerDefinition",
    "UpstreamSessionMode",
    "UpstreamSessionRecord",
    "UpstreamSessionStatus",
]
