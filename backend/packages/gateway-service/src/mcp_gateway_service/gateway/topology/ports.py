"""Persistence ports required by managed topology use cases."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .models import EndpointDefinition, UpstreamServerDefinition
from .revisions import EndpointTopologyRevision


class TopologyReader(Protocol):
    async def list_current_revisions(self) -> list[EndpointTopologyRevision]: ...

    async def resolve_current_revision(
        self,
        endpoint_slug: str,
    ) -> EndpointTopologyRevision | None: ...

    async def get_revision(self, revision_id: UUID) -> EndpointTopologyRevision | None: ...


class UpstreamServerRepository(Protocol):
    async def add(self, server: UpstreamServerDefinition) -> None: ...

    async def get(self, server_id: UUID) -> UpstreamServerDefinition | None: ...

    async def list(self) -> list[UpstreamServerDefinition]: ...


class EndpointRepository(Protocol):
    async def add(self, endpoint: EndpointDefinition) -> None: ...

    async def get(self, endpoint_id: UUID) -> EndpointDefinition | None: ...

    async def get_by_slug(self, slug: str) -> EndpointDefinition | None: ...

    async def list(self) -> list[EndpointDefinition]: ...
