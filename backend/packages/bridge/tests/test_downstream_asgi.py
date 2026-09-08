from __future__ import annotations

from uuid import UUID

import httpx
from mabrid.bridge import create_mcp_asgi_app
from starlette.types import Receive, Scope, Send

SESSION_ID = "12345678-1234-1234-1234-123456789abc"


class RecordingSession:
    def __init__(self) -> None:
        self.streamable_methods: list[str] = []
        self.sse_posts = 0

    async def handle_streamable_http(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        self.streamable_methods.append(scope.get("method", "GET"))
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"mcp-session-id", SESSION_ID.encode("ascii"))],
            }
        )
        await send({"type": "http.response.body", "body": b"{}"})

    async def handle_sse(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        assert scope["root_path"].endswith("/fixture")
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": (f"event: endpoint\ndata: /messages?session_id={SESSION_ID}\n\n".encode()),
            }
        )

    async def handle_sse_post(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        self.sse_posts += 1
        await send({"type": "http.response.start", "status": 202, "headers": []})
        await send({"type": "http.response.body", "body": b""})


class RecordingBroker:
    def __init__(self) -> None:
        self.session = RecordingSession()
        self.bound_ids: list[str] = []
        self.closed = 0

    async def open_session(self, endpoint_key: str) -> RecordingSession | None:
        return self.session if endpoint_key == "fixture" else None

    async def resolve_session(
        self,
        endpoint_key: str,
        transport_session_id: str,
    ) -> RecordingSession | None:
        if endpoint_key == "fixture" and transport_session_id == SESSION_ID:
            return self.session
        return None

    async def bind_transport_session(
        self,
        session: RecordingSession,
        transport_session_id: str,
    ) -> None:
        assert session is self.session
        self.bound_ids.append(transport_session_id)

    async def close_session(self, session: RecordingSession) -> None:
        assert session is self.session
        self.closed += 1

    def transport(self, session: RecordingSession) -> RecordingSession:
        assert session is self.session
        return session


def _client(broker: RecordingBroker) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_mcp_asgi_app(broker)),
        base_url="http://test",
    )


async def test_streamable_http_binds_resolves_and_closes_transport_session() -> None:
    broker = RecordingBroker()

    async with _client(broker) as client:
        initialized = await client.post("/fixture", content=b"{}")
        continued = await client.post(
            "/fixture",
            headers={"mcp-session-id": SESSION_ID},
            content=b"{}",
        )
        closed = await client.delete(
            "/fixture",
            headers={"mcp-session-id": SESSION_ID},
        )

    assert initialized.headers["mcp-session-id"] == SESSION_ID
    assert continued.status_code == 200
    assert closed.status_code == 200
    assert broker.bound_ids == [SESSION_ID]
    assert broker.session.streamable_methods == ["POST", "POST", "DELETE"]
    assert broker.closed == 1


async def test_unknown_endpoint_is_not_opened() -> None:
    broker = RecordingBroker()

    async with _client(broker) as client:
        response = await client.post("/unknown", content=b"{}")

    assert response.status_code == 404
    assert broker.bound_ids == []


async def test_legacy_sse_binds_endpoint_event_and_accepts_session_id_alias() -> None:
    UUID(SESSION_ID)
    broker = RecordingBroker()

    async with _client(broker) as client:
        opened = await client.get("/fixture/sse")
        posted = await client.post(
            "/fixture/messages",
            params={"sessionId": SESSION_ID},
            content=b"{}",
        )

    assert opened.status_code == 200
    assert posted.status_code == 202
    assert broker.bound_ids == [SESSION_ID]
    assert broker.session.sse_posts == 1
    assert broker.closed == 1
