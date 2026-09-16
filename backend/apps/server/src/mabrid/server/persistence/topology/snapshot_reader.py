"""Transactional SQLite reader for the complete managed Gateway topology."""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from mabrid.application.gateway.topology import (
    ManagedEndpoint,
    ManagedEndpointBinding,
    ManagedUpstream,
    RevisionMetadata,
    TopologySnapshot,
)
from mabrid.bridge import EndpointMode
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..schema import (
    EndpointBindingRevisionRow,
    EndpointBindingRow,
    EndpointRevisionRow,
    EndpointRow,
    UpstreamRevisionRow,
    UpstreamServerRow,
)
from .management_mappers import managed_connection_from_row
from .mappers import as_utc


class SqlAlchemyTopologySnapshotReader:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def read_snapshot(self) -> TopologySnapshot:
        async with self._session_factory.begin() as session:
            upstream_heads = list(
                await session.scalars(select(UpstreamServerRow).order_by(UpstreamServerRow.slug))
            )
            upstream_revisions = {
                row.revision_id: row for row in await session.scalars(select(UpstreamRevisionRow))
            }
            endpoint_heads = list(
                await session.scalars(select(EndpointRow).order_by(EndpointRow.slug))
            )
            endpoint_revisions = {
                row.revision_id: row for row in await session.scalars(select(EndpointRevisionRow))
            }
            binding_heads = list(await session.scalars(select(EndpointBindingRow)))
            binding_revisions = list(await session.scalars(select(EndpointBindingRevisionRow)))

            upstreams = tuple(
                _managed_upstream(head, upstream_revisions) for head in upstream_heads
            )
            endpoints = _managed_endpoints(
                endpoint_heads,
                endpoint_revisions,
                binding_heads,
                binding_revisions,
                upstream_revisions,
            )
            return TopologySnapshot(upstreams=upstreams, endpoints=endpoints)


def _managed_upstream(
    head: UpstreamServerRow,
    revisions: dict[UUID, UpstreamRevisionRow],
) -> ManagedUpstream:
    if head.current_revision_id is None:
        raise ValueError(f"Upstream has no current revision: {head.server_id}")
    revision = revisions.get(head.current_revision_id)
    if revision is None:
        raise ValueError(f"Upstream current revision does not exist: {head.current_revision_id}")
    if revision.server_id != head.server_id:
        raise ValueError(f"Upstream current revision belongs to another upstream: {head.server_id}")
    return ManagedUpstream(
        server_id=head.server_id,
        slug=head.slug,
        display_name=head.display_name,
        connection=managed_connection_from_row(head),
        enabled=head.enabled,
        metadata=head.metadata_json,
        current_revision=_revision_metadata(revision),
    )


def _managed_endpoints(
    endpoint_heads: list[EndpointRow],
    endpoint_revisions: dict[UUID, EndpointRevisionRow],
    binding_heads: list[EndpointBindingRow],
    binding_revisions: list[EndpointBindingRevisionRow],
    upstream_revisions: dict[UUID, UpstreamRevisionRow],
) -> tuple[ManagedEndpoint, ...]:
    heads_by_endpoint: defaultdict[UUID, list[EndpointBindingRow]] = defaultdict(list)
    for binding in binding_heads:
        heads_by_endpoint[binding.endpoint_id].append(binding)
    revisions_by_endpoint_revision: defaultdict[UUID, list[EndpointBindingRevisionRow]] = (
        defaultdict(list)
    )
    for binding_revision in binding_revisions:
        revisions_by_endpoint_revision[binding_revision.endpoint_revision_id].append(
            binding_revision
        )

    return tuple(
        _managed_endpoint(
            head,
            endpoint_revisions,
            heads_by_endpoint[head.endpoint_id],
            revisions_by_endpoint_revision,
            upstream_revisions,
        )
        for head in endpoint_heads
    )


def _managed_endpoint(
    head: EndpointRow,
    endpoint_revisions: dict[UUID, EndpointRevisionRow],
    binding_heads: list[EndpointBindingRow],
    revisions_by_endpoint_revision: dict[UUID, list[EndpointBindingRevisionRow]],
    upstream_revisions: dict[UUID, UpstreamRevisionRow],
) -> ManagedEndpoint:
    if head.current_revision_id is None:
        raise ValueError(f"Endpoint has no current revision: {head.endpoint_id}")
    revision = endpoint_revisions.get(head.current_revision_id)
    if revision is None:
        raise ValueError(f"Endpoint current revision does not exist: {head.current_revision_id}")
    if revision.endpoint_id != head.endpoint_id:
        raise ValueError(
            f"Endpoint current revision belongs to another endpoint: {head.endpoint_id}"
        )

    head_by_id = {binding.binding_id: binding for binding in binding_heads}
    revision_rows = revisions_by_endpoint_revision.get(revision.revision_id, [])
    revision_by_id = {binding.binding_id: binding for binding in revision_rows}
    if head_by_id.keys() != revision_by_id.keys():
        raise ValueError(f"Endpoint bindings do not match current revision: {head.endpoint_id}")

    bindings: list[ManagedEndpointBinding] = []
    for binding_head in sorted(
        binding_heads,
        key=lambda item: (item.priority, item.namespace or "", str(item.binding_id)),
    ):
        binding_revision = revision_by_id[binding_head.binding_id]
        upstream_revision = upstream_revisions.get(binding_revision.upstream_revision_id)
        if upstream_revision is None:
            raise ValueError(
                "Endpoint binding references an unknown upstream revision: "
                f"{binding_revision.upstream_revision_id}"
            )
        if upstream_revision.server_id != binding_head.upstream_server_id:
            raise ValueError(
                f"Endpoint binding references another upstream: {binding_head.binding_id}"
            )
        bindings.append(
            ManagedEndpointBinding(
                binding_id=binding_head.binding_id,
                binding_revision_id=binding_revision.binding_revision_id,
                upstream_server_id=binding_head.upstream_server_id,
                upstream_revision_id=binding_revision.upstream_revision_id,
                namespace=binding_head.namespace,
                priority=binding_head.priority,
                enabled=binding_head.enabled,
            )
        )

    return ManagedEndpoint(
        endpoint_id=head.endpoint_id,
        slug=head.slug,
        display_name=head.display_name,
        mode=EndpointMode(head.mode),
        bindings=tuple(bindings),
        enabled=head.enabled,
        metadata=head.metadata_json,
        current_revision=_revision_metadata(revision),
    )


def _revision_metadata(row: UpstreamRevisionRow | EndpointRevisionRow) -> RevisionMetadata:
    return RevisionMetadata(
        revision_id=row.revision_id,
        revision_number=row.revision_number,
        created_at=as_utc(row.created_at),
    )
