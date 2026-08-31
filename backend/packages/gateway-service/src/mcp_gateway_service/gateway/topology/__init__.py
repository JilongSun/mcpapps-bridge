"""Managed upstream and endpoint topology contracts.

This context owns mutable topology heads, immutable published revisions, persistence ports, and the
single conversion from a selected revision to a bridge-core runtime plan. It does not own live MCP
sessions or SQLAlchemy rows.
"""

from .models import (
    EndpointBinding,
    EndpointDefinition,
    ServiceModel,
    SseConnection,
    StdioConnection,
    StreamableHttpConnection,
    UpstreamConnection,
    UpstreamServerDefinition,
)
from .ports import EndpointRepository, TopologyReader, UpstreamServerRepository
from .revisions import (
    EndpointBindingRevision,
    EndpointTopologyRevision,
    UpstreamRevision,
    build_endpoint_plan_from_revision,
)

__all__ = [
    "EndpointBinding",
    "EndpointBindingRevision",
    "EndpointDefinition",
    "EndpointRepository",
    "EndpointTopologyRevision",
    "ServiceModel",
    "SseConnection",
    "StdioConnection",
    "StreamableHttpConnection",
    "TopologyReader",
    "UpstreamConnection",
    "UpstreamRevision",
    "UpstreamServerDefinition",
    "UpstreamServerRepository",
    "build_endpoint_plan_from_revision",
]
