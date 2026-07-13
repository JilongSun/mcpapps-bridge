"""FastAPI control plane for the managed bridge runtime."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.routing import Mount
from starlette.types import ASGIApp, Receive, Scope, Send

from mcpapps_bridge.mcp import BridgeManager, PublishedEndpoint


def create_app(manager: BridgeManager) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with manager.lifecycle():
            yield

    app = FastAPI(title="mcpapps bridge", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["mcp-session-id"],
    )
    app.state.bridge_manager = manager

    for endpoint in manager.published_endpoints:
        app.router.routes.append(Mount(endpoint.path, app=create_mcp_transport_app(endpoint)))

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/sessions")
    async def list_sessions() -> list[dict[str, object]]:
        sessions = await manager.list_sessions()
        return [session.model_dump(mode="json") for session in sessions]

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: UUID) -> dict[str, object]:
        session = await manager.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Bridge session not found")
        store = await manager.get_session_store(session_id)
        snapshot = await store.snapshot()
        return {
            "session": session.model_dump(mode="json"),
            "snapshot": snapshot.model_dump(mode="json"),
        }

    @app.get("/api/sessions/{session_id}/events")
    async def get_events(session_id: UUID, after: int = 0) -> list[dict[str, object]]:
        try:
            store = await manager.get_session_store(session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Bridge session not found") from None
        events = await store.events(after_index=after)
        return [event.model_dump(mode="json") for event in events]

    @app.websocket("/api/sessions/{session_id}/events/ws")
    async def events_websocket(websocket: WebSocket, session_id: UUID) -> None:
        try:
            store = await manager.get_session_store(session_id)
        except KeyError:
            await websocket.close(code=4404, reason="Bridge session not found")
            return
        after = int(websocket.query_params.get("after", "0"))
        await websocket.accept()
        try:
            while True:
                events = await store.wait_for_events(after_index=after)
                payload = [event.model_dump(mode="json") for event in events]
                after += len(events)
                await websocket.send_json({"after": after, "events": payload})
        except WebSocketDisconnect:
            return

    return app


def create_mcp_transport_app(endpoint: PublishedEndpoint) -> ASGIApp:
    async def mcp_transport_app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await _not_found(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")
        if method in {"GET", "POST", "DELETE"} and path in {"", "/"}:
            await endpoint.downstream.handle_streamable_http(scope, receive, send)
            return
        if method == "GET" and path == "/sse":
            await endpoint.downstream.handle_sse(scope, receive, send)
            return
        if method == "POST" and path in {"/messages", "/messages/"}:
            await endpoint.downstream.handle_sse_post(scope, receive, send)
            return
        await _not_found(scope, receive, send)

    return mcp_transport_app


async def _not_found(scope: Scope, receive: Receive, send: Send) -> None:
    response = Response(status_code=404)
    await response(scope, receive, send)
