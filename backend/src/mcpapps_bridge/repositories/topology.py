"""Repository-backed topology reader for the process-local memory profile."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

from mcpapps_bridge.domain import (
    EndpointBindingRevision,
    EndpointTopologyRevision,
    UpstreamRevision,
)

from .protocols import EndpointRepository, UpstreamServerRepository

REVISION_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class RepositoryTopologyReader:
    def __init__(
        self,
        upstream_servers: UpstreamServerRepository,
        endpoints: EndpointRepository,
    ) -> None:
        self._upstream_servers = upstream_servers
        self._endpoints = endpoints

    async def list_current_revisions(self) -> list[EndpointTopologyRevision]:
        revisions = [
            await self._resolve(endpoint)
            for endpoint in await self._endpoints.list()
            if endpoint.enabled
        ]
        return sorted(revisions, key=lambda revision: revision.slug)

    async def resolve_current_revision(
        self,
        endpoint_slug: str,
    ) -> EndpointTopologyRevision | None:
        endpoint = await self._endpoints.get_by_slug(endpoint_slug)
        return await self._resolve(endpoint) if endpoint is not None and endpoint.enabled else None

    async def get_revision(self, revision_id: UUID) -> EndpointTopologyRevision | None:
        for revision in await self.list_current_revisions():
            if revision.revision_id == revision_id:
                return revision
        return None

    async def _resolve(self, endpoint: object) -> EndpointTopologyRevision:
        from mcpapps_bridge.domain import EndpointDefinition

        if not isinstance(endpoint, EndpointDefinition):
            raise TypeError(f"Unsupported endpoint definition: {type(endpoint).__name__}")
        bindings: list[EndpointBindingRevision] = []
        for binding in endpoint.bindings:
            server = await self._upstream_servers.get(binding.upstream_server_id)
            if server is None:
                raise ValueError(f"Unknown upstream server: {binding.upstream_server_id}")
            upstream_revision = UpstreamRevision(
                revision_id=_revision_id("upstream", server.server_id),
                server_id=server.server_id,
                slug=server.slug,
                display_name=server.display_name,
                connection=server.connection,
                enabled=server.enabled,
                metadata=server.metadata,
                created_at=REVISION_EPOCH,
            )
            bindings.append(
                EndpointBindingRevision(
                    binding_revision_id=_revision_id(
                        "binding", endpoint.endpoint_id, binding.binding_id
                    ),
                    binding_id=binding.binding_id,
                    namespace=binding.namespace,
                    priority=binding.priority,
                    enabled=binding.enabled,
                    upstream=upstream_revision,
                )
            )
        return EndpointTopologyRevision(
            revision_id=_revision_id("endpoint", endpoint.endpoint_id),
            endpoint_id=endpoint.endpoint_id,
            slug=endpoint.slug,
            display_name=endpoint.display_name,
            mode=endpoint.mode,
            bindings=tuple(bindings),
            session_policy=endpoint.session_policy,
            enabled=endpoint.enabled,
            metadata=endpoint.metadata,
            created_at=REVISION_EPOCH,
        )


def _revision_id(kind: str, *identifiers: UUID) -> UUID:
    value = ":".join([kind, *(str(identifier) for identifier in identifiers)])
    return uuid5(NAMESPACE_URL, value)
