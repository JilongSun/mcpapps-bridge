"""Atomic first-run import of explicitly configured topology into an empty database."""

from uuid import UUID, uuid4

from mabrid.application.gateway.topology import EndpointDefinition, UpstreamServerDefinition
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..schema import EndpointBindingRevisionRow, EndpointRow, UpstreamServerRow
from .mappers import (
    binding_to_row,
    endpoint_head_to_row,
    endpoint_revision_to_row,
    upstream_head_to_row,
    upstream_revision_to_row,
)


async def seed_topology_if_empty(
    session_factory: async_sessionmaker[AsyncSession],
    upstream_servers: list[UpstreamServerDefinition],
    endpoints: list[EndpointDefinition],
) -> bool:
    async with session_factory.begin() as session:
        existing_upstream = await session.scalar(select(UpstreamServerRow.server_id).limit(1))
        existing_endpoint = await session.scalar(select(EndpointRow.endpoint_id).limit(1))
        if existing_upstream is not None or existing_endpoint is not None:
            return False
        upstream_rows = {
            server.server_id: upstream_head_to_row(server) for server in upstream_servers
        }
        session.add_all(upstream_rows.values())
        await session.flush()
        upstream_revision_ids: dict[UUID, UUID] = {}
        for server in upstream_servers:
            revision_id = uuid4()
            upstream_revision_ids[server.server_id] = revision_id
            session.add(upstream_revision_to_row(server, revision_id))
        await session.flush()
        for server_id, revision_id in upstream_revision_ids.items():
            upstream_rows[server_id].current_revision_id = revision_id

        endpoint_rows = {
            endpoint.endpoint_id: endpoint_head_to_row(endpoint) for endpoint in endpoints
        }
        session.add_all(endpoint_rows.values())
        await session.flush()
        endpoint_revision_ids: dict[UUID, UUID] = {}
        for endpoint in endpoints:
            revision_id = uuid4()
            endpoint_revision_ids[endpoint.endpoint_id] = revision_id
            session.add(endpoint_revision_to_row(endpoint, revision_id))
        await session.flush()
        for endpoint in endpoints:
            session.add_all(
                binding_to_row(endpoint.endpoint_id, item) for item in endpoint.bindings
            )
            session.add_all(
                EndpointBindingRevisionRow(
                    binding_revision_id=uuid4(),
                    binding_id=item.binding_id,
                    endpoint_revision_id=endpoint_revision_ids[endpoint.endpoint_id],
                    upstream_revision_id=upstream_revision_ids[item.upstream_server_id],
                    namespace=item.namespace,
                    priority=item.priority,
                    enabled=item.enabled,
                )
                for item in endpoint.bindings
            )
            endpoint_rows[endpoint.endpoint_id].current_revision_id = endpoint_revision_ids[
                endpoint.endpoint_id
            ]
        return True
