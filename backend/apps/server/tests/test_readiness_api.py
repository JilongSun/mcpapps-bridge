from __future__ import annotations

from typing import cast

import httpx
from mabrid.application.gateway.inspection import SessionInspectionReader
from mabrid.application.gateway.sessions import GatewaySessionCoordinator, SessionHistoryReader
from mabrid.application.gateway.topology import TopologySnapshotReader

from mabrid.server.api import create_app
from mabrid.server.composition import GatewayManagementComposition
from mabrid.server.persistence import SqliteReadinessProbe


class FixtureProbe:
    def __init__(self, ready: bool) -> None:
        self.ready = ready

    async def is_ready(self) -> bool:
        return self.ready


def _management(
    *,
    published_endpoint_slugs: tuple[str, ...] = ("fixture",),
    persistence_ready: bool = True,
) -> GatewayManagementComposition:
    return GatewayManagementComposition(
        topology_reader=cast(TopologySnapshotReader, object()),
        session_history_reader=cast(SessionHistoryReader, object()),
        session_inspection_reader=cast(SessionInspectionReader, object()),
        readiness_probe=cast(SqliteReadinessProbe, FixtureProbe(persistence_ready)),
        advertised_base_url=None,
        published_endpoint_slugs=published_endpoint_slugs,
    )


async def _get_ready(management: GatewayManagementComposition) -> httpx.Response:
    app = create_app(
        cast(GatewaySessionCoordinator, object()),
        gateway_management=management,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        health = await client.get("/health")
        assert health.status_code == 200
        return await client.get("/ready")


async def test_ready_reports_a_healthy_local_composition() -> None:
    response = await _get_ready(_management())

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_ready_rejects_a_gateway_without_published_endpoints() -> None:
    response = await _get_ready(_management(published_endpoint_slugs=()))

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "not_ready"


async def test_ready_rejects_an_unavailable_database() -> None:
    response = await _get_ready(_management(persistence_ready=False))

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "persistence_unavailable"
