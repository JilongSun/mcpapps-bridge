"""SQLAlchemy reader for complete immutable Gateway topology revisions.

The adapter resolves relational rows into application-owned revision contracts. It does not
construct bridge-core plans; that conversion remains owned by the application topology context.
"""

from __future__ import annotations

from uuid import UUID

from mabrid.bridge import EndpointMode
from mabrid.application.gateway.topology import (
    EndpointBindingRevision,
    EndpointTopologyRevision,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..schema import (
    EndpointBindingRevisionRow,
    EndpointRevisionRow,
    EndpointRow,
    UpstreamRevisionRow,
)
from .mappers import as_utc, upstream_revision_from_row


class SqlAlchemyTopologyReader:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_current_revisions(self) -> list[EndpointTopologyRevision]:
        async with self._session_factory() as session:
            revision_ids = (
                await session.scalars(
                    select(EndpointRow.current_revision_id)
                    .where(EndpointRow.enabled.is_(True))
                    .where(EndpointRow.current_revision_id.is_not(None))
                    .order_by(EndpointRow.slug)
                )
            ).all()
            revisions: list[EndpointTopologyRevision] = []
            for revision_id in revision_ids:
                if revision_id is None:
                    raise ValueError("Enabled endpoint has no current revision")
                revisions.append(await _load_revision(session, revision_id))
            return revisions

    async def resolve_current_revision(
        self,
        endpoint_slug: str,
    ) -> EndpointTopologyRevision | None:
        async with self._session_factory() as session:
            revision_id = await session.scalar(
                select(EndpointRow.current_revision_id).where(
                    EndpointRow.slug == endpoint_slug,
                    EndpointRow.enabled.is_(True),
                )
            )
            return await _load_revision(session, revision_id) if revision_id is not None else None

    async def get_revision(self, revision_id: UUID) -> EndpointTopologyRevision | None:
        async with self._session_factory() as session:
            row = await session.get(EndpointRevisionRow, revision_id)
            return await _revision_from_row(session, row) if row is not None else None


async def _load_revision(
    session: AsyncSession,
    revision_id: UUID,
) -> EndpointTopologyRevision:
    row = await session.get(EndpointRevisionRow, revision_id)
    if row is None:
        raise ValueError(f"Endpoint current revision does not exist: {revision_id}")
    return await _revision_from_row(session, row)


async def _revision_from_row(
    session: AsyncSession,
    row: EndpointRevisionRow,
) -> EndpointTopologyRevision:
    binding_rows = (
        await session.scalars(
            select(EndpointBindingRevisionRow)
            .where(EndpointBindingRevisionRow.endpoint_revision_id == row.revision_id)
            .order_by(
                EndpointBindingRevisionRow.priority,
                EndpointBindingRevisionRow.namespace,
                EndpointBindingRevisionRow.binding_revision_id,
            )
        )
    ).all()
    bindings: list[EndpointBindingRevision] = []
    for binding_row in binding_rows:
        upstream_row = await session.get(
            UpstreamRevisionRow,
            binding_row.upstream_revision_id,
        )
        if upstream_row is None:
            raise ValueError(
                f"Binding revision references unknown upstream revision: "
                f"{binding_row.upstream_revision_id}"
            )
        bindings.append(
            EndpointBindingRevision(
                binding_revision_id=binding_row.binding_revision_id,
                binding_id=binding_row.binding_id,
                namespace=binding_row.namespace,
                priority=binding_row.priority,
                enabled=binding_row.enabled,
                upstream=upstream_revision_from_row(upstream_row),
            )
        )
    return EndpointTopologyRevision(
        revision_id=row.revision_id,
        endpoint_id=row.endpoint_id,
        revision_number=row.revision_number,
        slug=row.slug,
        display_name=row.display_name,
        mode=EndpointMode(row.mode),
        bindings=tuple(bindings),
        enabled=row.enabled,
        metadata=row.metadata_json,
        created_at=as_utc(row.created_at),
    )
