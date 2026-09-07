"""Process-lifetime publication of immutable Gateway endpoint revisions.

Published topology is loaded once from the application reader and materialized into bridge-core
plans. It owns slug lookup but no live sessions, transport correlation, or persistence mutation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from mabrid.bridge import EndpointPlan

from ..topology.ports import TopologyReader
from ..topology.revisions import EndpointTopologyRevision, build_endpoint_plan_from_revision

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublishedEndpoint:
    revision: EndpointTopologyRevision
    plan: EndpointPlan

    @property
    def path(self) -> str:
        return f"/mcp/{self.revision.slug}"


class PublishedTopology:
    def __init__(self, reader: TopologyReader) -> None:
        self._reader = reader
        self._endpoints: dict[UUID, PublishedEndpoint] = {}
        self._slug_index: dict[str, UUID] = {}

    @property
    def endpoints(self) -> list[PublishedEndpoint]:
        return list(self._endpoints.values())

    async def load(self) -> None:
        self._endpoints.clear()
        self._slug_index.clear()
        revisions = await self._reader.list_current_revisions()
        logger.info("Loading %d published endpoint(s) from topology", len(revisions))
        for revision in revisions:
            published = self._materialize(revision)
            bindings = [binding for binding in revision.bindings if binding.enabled]
            logger.info(
                "Published endpoint: slug=%s display_name=%s mode=%s upstreams=%s",
                revision.slug,
                revision.display_name,
                revision.mode.value,
                [binding.upstream.display_name for binding in bindings],
            )
            self._endpoints[revision.endpoint_id] = published
            self._slug_index[revision.slug] = revision.endpoint_id

    def resolve(self, slug: str) -> PublishedEndpoint | None:
        endpoint_id = self._slug_index.get(slug)
        return self._endpoints.get(endpoint_id) if endpoint_id is not None else None

    @staticmethod
    def _materialize(revision: EndpointTopologyRevision) -> PublishedEndpoint:
        if not revision.enabled:
            raise ValueError(f"Cannot publish disabled endpoint: {revision.slug}")
        disabled_upstreams = [
            binding.upstream.slug
            for binding in revision.bindings
            if binding.enabled and not binding.upstream.enabled
        ]
        if disabled_upstreams:
            names = ", ".join(sorted(disabled_upstreams))
            raise ValueError(f"Cannot bind disabled upstream servers: {names}")
        return PublishedEndpoint(
            revision=revision,
            plan=build_endpoint_plan_from_revision(revision),
        )
