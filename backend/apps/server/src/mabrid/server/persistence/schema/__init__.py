"""Complete server-owned SQLite schema exposed to adapters and Alembic.

Importing this facade registers every row on the shared ``Base.metadata`` registry.
"""

from .base import Base
from .sessions import BridgeSessionRow, SessionEventRow, SessionSnapshotRow
from .topology import (
    EndpointBindingRevisionRow,
    EndpointBindingRow,
    EndpointRevisionRow,
    EndpointRow,
    UpstreamRevisionRow,
    UpstreamServerRow,
)

__all__ = [
    "Base",
    "BridgeSessionRow",
    "EndpointBindingRevisionRow",
    "EndpointBindingRow",
    "EndpointRevisionRow",
    "EndpointRow",
    "SessionEventRow",
    "SessionSnapshotRow",
    "UpstreamRevisionRow",
    "UpstreamServerRow",
]
