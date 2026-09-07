"""Persistence ports required by managed topology use cases."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .revisions import EndpointTopologyRevision


class TopologyReader(Protocol):
    async def list_current_revisions(self) -> list[EndpointTopologyRevision]: ...

    async def resolve_current_revision(
        self,
        endpoint_slug: str,
    ) -> EndpointTopologyRevision | None: ...

    async def get_revision(self, revision_id: UUID) -> EndpointTopologyRevision | None: ...
