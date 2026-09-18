from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import cast
from uuid import UUID

import httpx
from mabrid.application.agent_host import (
    AgentCapability,
    AgentEndpointAssignment,
    AgentRuntimeInterface,
    AgentRuntimeProfile,
    AgentTarget,
)
from mabrid.application.gateway.inspection import (
    BridgeSessionSnapshot,
    ErrorRaisedEvent,
    SequencedSessionEvent,
    SessionEventPage,
    SessionEventPageRequest,
    SessionInspectionReader,
)
from mabrid.application.gateway.sessions import (
    BridgeSessionRecord,
    BridgeSessionStatus,
    GatewaySessionCoordinator,
    SessionHistoryReader,
    SessionKeyset,
    SessionPage,
    SessionPageRequest,
)
from mabrid.application.gateway.topology import (
    ConfiguredKey,
    ManagedEndpoint,
    ManagedEndpointBinding,
    ManagedStdioConnection,
    ManagedUpstream,
    RevisionMetadata,
    TopologySnapshot,
    TopologySnapshotReader,
)
from mabrid.bridge import EndpointMode
import pytest

from mabrid.server.api import create_app
from mabrid.server.composition import AgentHostManagementView, GatewayManagementComposition
from mabrid.server.persistence import SqliteReadinessProbe

NOW = datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc)
ENDPOINT_ID = UUID(int=1)
ENDPOINT_REVISION_ID = UUID(int=2)
UPSTREAM_ID = UUID(int=3)
UPSTREAM_REVISION_ID = UUID(int=4)
SESSION_ID = UUID(int=5)


class FixtureTopologyReader:
    async def read_snapshot(self) -> TopologySnapshot:
        return TopologySnapshot(
            upstreams=(
                ManagedUpstream(
                    server_id=UPSTREAM_ID,
                    slug="fixture-upstream",
                    display_name="Fixture Upstream",
                    connection=ManagedStdioConnection(
                        command="fixture-server",
                        env=(ConfiguredKey(name="API_TOKEN"),),
                    ),
                    enabled=False,
                    current_revision=RevisionMetadata(
                        revision_id=UPSTREAM_REVISION_ID,
                        revision_number=1,
                        created_at=NOW,
                    ),
                ),
            ),
            endpoints=(
                ManagedEndpoint(
                    endpoint_id=ENDPOINT_ID,
                    slug="fixture-endpoint",
                    display_name="Fixture Endpoint",
                    mode=EndpointMode.PASSTHROUGH,
                    bindings=(
                        ManagedEndpointBinding(
                            binding_id=UUID(int=6),
                            binding_revision_id=UUID(int=7),
                            upstream_server_id=UPSTREAM_ID,
                            upstream_revision_id=UPSTREAM_REVISION_ID,
                        ),
                    ),
                    enabled=False,
                    current_revision=RevisionMetadata(
                        revision_id=ENDPOINT_REVISION_ID,
                        revision_number=1,
                        created_at=NOW,
                    ),
                ),
            ),
        )


class FailingTopologyReader:
    async def read_snapshot(self) -> TopologySnapshot:
        raise ValueError("credential fixture-secret found in corrupt row")


class FixtureSessionHistoryReader:
    def __init__(self) -> None:
        self.requests: list[SessionPageRequest] = []

    async def list_sessions(self, request: SessionPageRequest) -> SessionPage:
        self.requests.append(request)
        record = _session_record()
        if request.before is not None:
            return SessionPage(items=(record,))
        return SessionPage(
            items=(record,),
            next_keyset=SessionKeyset(created_at=NOW, session_id=SESSION_ID),
        )

    async def get_session(self, session_id: UUID) -> BridgeSessionRecord | None:
        return _session_record() if session_id == SESSION_ID else None


class FixtureInspectionReader:
    async def get_snapshot(self, session_id: UUID) -> BridgeSessionSnapshot | None:
        if session_id != SESSION_ID:
            return None
        return BridgeSessionSnapshot(
            session_id=str(session_id),
            last_error="fixture failure",
            event_count=1,
            updated_at=NOW,
        )

    async def list_events(self, request: SessionEventPageRequest) -> SessionEventPage | None:
        if request.session_id != SESSION_ID:
            return None
        event = ErrorRaisedEvent(
            event_id="fixture-event",
            session_id=str(SESSION_ID),
            message="fixture failure",
            details={"kind": "fixture"},
            created_at=NOW,
        )
        return SessionEventPage(
            items=(SequencedSessionEvent(sequence=request.after + 1, event=event),),
            next_after=request.after + 1 if request.limit == 1 else None,
        )


class ReadyProbe:
    async def is_ready(self) -> bool:
        return True


def _session_record() -> BridgeSessionRecord:
    return BridgeSessionRecord(
        session_id=SESSION_ID,
        endpoint_id=ENDPOINT_ID,
        endpoint_revision_id=ENDPOINT_REVISION_ID,
        status=BridgeSessionStatus.ACTIVE,
        created_at=NOW,
        last_activity_at=NOW,
    )


def _gateway_management(
    history: FixtureSessionHistoryReader | None = None,
    topology: TopologySnapshotReader | None = None,
) -> GatewayManagementComposition:
    return GatewayManagementComposition(
        topology_reader=topology or cast(TopologySnapshotReader, FixtureTopologyReader()),
        session_history_reader=cast(SessionHistoryReader, history or FixtureSessionHistoryReader()),
        session_inspection_reader=cast(SessionInspectionReader, FixtureInspectionReader()),
        readiness_probe=cast(SqliteReadinessProbe, ReadyProbe()),
        advertised_base_url="http://mabrid.test:8765",
        published_endpoint_slugs=("fixture-endpoint",),
    )


def _agent_host_management() -> AgentHostManagementView:
    target = AgentTarget(
        target_id="fixture-target",
        runtime_profile=AgentRuntimeProfile(
            integration_kind="hermes",
            interface=AgentRuntimeInterface.OPENAI_CHAT_COMPLETIONS,
            capabilities=frozenset({AgentCapability.TEXT_GENERATION}),
        ),
        endpoint_assignment=AgentEndpointAssignment(endpoint_slug="fixture-endpoint"),
    )
    return AgentHostManagementView(
        target=target,
        endpoint_id=ENDPOINT_ID,
        endpoint_slug="fixture-endpoint",
        endpoint_path="/mcp/fixture-endpoint",
        transport="streamable-http",
        advertised_url="http://mabrid.test:8765/mcp/fixture-endpoint",
    )


def _client(
    management: GatewayManagementComposition,
    *,
    agent_host_management: AgentHostManagementView | None = None,
) -> httpx.AsyncClient:
    app = create_app(
        cast(GatewaySessionCoordinator, object()),
        gateway_management=management,
        agent_host_management=agent_host_management,
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


async def test_gateway_status_and_topology_contracts_hide_secret_values() -> None:
    async with _client(_gateway_management()) as client:
        status = await client.get("/api/v1/gateway/status")
        topology = await client.get("/api/v1/gateway/topology")

    assert status.status_code == 200
    assert status.json() == {
        "version": "0.1.0",
        "lifecycle_state": "running",
        "topology_mode": "frozen_seeded",
        "advertised_base_url": "http://mabrid.test:8765",
        "published_endpoint_count": 1,
        "published_endpoint_slugs": ["fixture-endpoint"],
    }
    assert topology.status_code == 200
    payload = topology.json()
    assert payload["endpoints"][0]["endpoint_path"] == "/mcp/fixture-endpoint"
    assert payload["endpoints"][0]["advertised_url"] == (
        "http://mabrid.test:8765/mcp/fixture-endpoint"
    )
    assert payload["upstreams"][0]["connection"]["env"] == [
        {"name": "API_TOKEN", "configured": True}
    ]
    assert "secret" not in topology.text.lower()


async def test_session_cursor_continues_an_opaque_keyset_page() -> None:
    history = FixtureSessionHistoryReader()
    async with _client(_gateway_management(history)) as client:
        first = await client.get(
            "/api/v1/gateway/sessions",
            params={"limit": 1, "endpoint_id": str(ENDPOINT_ID), "status": "active"},
        )
        cursor = first.json()["next_cursor"]
        second = await client.get(
            "/api/v1/gateway/sessions",
            params={"limit": 1, "cursor": cursor},
        )

    assert first.status_code == 200
    assert cursor and str(SESSION_ID) not in cursor
    assert second.status_code == 200
    assert history.requests[0].endpoint_id == ENDPOINT_ID
    assert history.requests[0].status is BridgeSessionStatus.ACTIVE
    assert history.requests[1].before is not None
    assert history.requests[1].before.session_id == SESSION_ID


async def test_session_record_snapshot_and_event_contracts() -> None:
    async with _client(_gateway_management()) as client:
        record = await client.get(f"/api/v1/gateway/sessions/{SESSION_ID}")
        snapshot = await client.get(f"/api/v1/gateway/sessions/{SESSION_ID}/snapshot")
        events = await client.get(
            f"/api/v1/gateway/sessions/{SESSION_ID}/events",
            params={"after": 3, "limit": 1},
        )

    assert record.status_code == 200
    assert record.json()["endpoint_revision_id"] == str(ENDPOINT_REVISION_ID)
    assert snapshot.status_code == 200
    assert snapshot.json()["last_error"] == "fixture failure"
    assert events.status_code == 200
    assert events.json()["items"][0] == {
        "sequence": 4,
        "event": {
            "event_id": "fixture-event",
            "session_id": str(SESSION_ID),
            "created_at": "2026-09-18T08:00:00Z",
            "kind": "error.raised",
            "message": "fixture failure",
            "details": {"kind": "fixture"},
        },
    }
    assert events.json()["next_after"] == 4


def _encoded_cursor(payload: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return encoded.rstrip("=")


@pytest.mark.parametrize(
    "cursor",
    [
        "not-a-cursor",
        _encoded_cursor({"v": 2, "created_at": NOW.isoformat(), "session_id": str(SESSION_ID)}),
        _encoded_cursor({"v": 1, "created_at": NOW.isoformat()}),
        _encoded_cursor(
            {
                "v": 1,
                "created_at": NOW.isoformat(),
                "session_id": str(SESSION_ID),
                "extra": True,
            }
        ),
        _encoded_cursor({"v": 1, "created_at": "invalid", "session_id": str(SESSION_ID)}),
        _encoded_cursor({"v": 1, "created_at": NOW.isoformat(), "session_id": "invalid"}),
    ],
)
async def test_invalid_session_cursors_use_problem_details(cursor: str) -> None:
    async with _client(_gateway_management()) as client:
        response = await client.get("/api/v1/gateway/sessions", params={"cursor": cursor})

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "urn:mabrid:problem:invalid-cursor",
        "title": "Invalid cursor",
        "status": 400,
        "detail": "The session cursor is malformed or unsupported.",
        "code": "invalid_cursor",
    }


async def test_management_errors_use_problem_details() -> None:
    missing = UUID(int=999)
    async with _client(_gateway_management()) as client:
        invalid_limit = await client.get("/api/v1/gateway/sessions", params={"limit": 0})
        responses = [
            await client.get(f"/api/v1/gateway/sessions/{missing}"),
            await client.get(f"/api/v1/gateway/sessions/{missing}/snapshot"),
            await client.get(f"/api/v1/gateway/sessions/{missing}/events"),
        ]

    assert invalid_limit.status_code == 422
    assert invalid_limit.json()["code"] == "invalid_request"
    assert all(response.status_code == 404 for response in responses)
    assert all(response.json()["code"] == "session_not_found" for response in responses)


async def test_agent_host_target_and_disabled_contracts() -> None:
    async with _client(
        _gateway_management(), agent_host_management=_agent_host_management()
    ) as client:
        enabled = await client.get("/api/v1/agent-host/target")
    async with _client(_gateway_management()) as client:
        disabled = await client.get("/api/v1/agent-host/target")

    assert enabled.status_code == 200
    assert enabled.json()["target_id"] == "fixture-target"
    assert enabled.json()["assignment"] == {
        "endpoint_id": str(ENDPOINT_ID),
        "endpoint_slug": "fixture-endpoint",
        "endpoint_path": "/mcp/fixture-endpoint",
        "transport": "streamable-http",
        "advertised_url": "http://mabrid.test:8765/mcp/fixture-endpoint",
    }
    assert disabled.status_code == 404
    assert disabled.json()["code"] == "agent_host_disabled"


async def test_unexpected_management_failure_hides_internal_details() -> None:
    management = _gateway_management(topology=FailingTopologyReader())
    async with _client(management) as client:
        response = await client.get("/api/v1/gateway/topology")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "internal_error"
    assert "fixture-secret" not in response.text


async def test_management_routes_are_absent_without_management_composition() -> None:
    app = create_app(cast(GatewaySessionCoordinator, object()))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        responses = [
            await client.get("/api/v1/gateway/status"),
            await client.get("/api/v1/agent-host/target"),
            await client.get("/ready"),
        ]

    assert all(response.status_code == 404 for response in responses)
