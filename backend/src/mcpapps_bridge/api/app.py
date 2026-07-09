"""FastAPI control plane for the bridge runtime."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from mcpapps_bridge.mcp import BridgeManager, BridgeRoute
from mcpapps_bridge.session import BridgeSessionState, BridgeSessionStore


def create_app(
    manager: BridgeManager | None = None,
    session_state: BridgeSessionState | None = None,
) -> FastAPI:
    default_route = manager.default_route if manager is not None else None
    state: BridgeSessionStore = (
        session_state
        or (default_route.session_store if default_route is not None else None)
        or BridgeSessionState(session_id="local-dev-session")
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if manager is None:
            yield
            return

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
    app.state.session_state = state
    app.state.bridge_manager = manager

    if manager is not None:
        for route in manager.routes:
            app.router.routes.append(Mount(route.path, app=create_mcp_transport_app(route)))

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/session")
    async def get_session() -> dict[str, object]:
        snapshot = await state.snapshot()
        return snapshot.model_dump(mode="json")

    @app.get("/api/events")
    async def get_events(after: int = 0) -> list[dict[str, object]]:
        events = await state.events(after_index=after)
        return [event.model_dump(mode="json") for event in events]

    @app.websocket("/api/events/ws")
    async def events_websocket(websocket: WebSocket) -> None:
        after = int(websocket.query_params.get("after", "0"))
        await websocket.accept()
        try:
            while True:
                events = await state.wait_for_events(after_index=after)
                payload = [event.model_dump(mode="json") for event in events]
                after += len(events)
                await websocket.send_json({"after": after, "events": payload})
        except WebSocketDisconnect:
            return

    return app


def create_mcp_transport_app(route: BridgeRoute):
    async def mcp_transport_app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            response = Response(status_code=404)
            await response(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        if method in {"GET", "POST", "DELETE"} and path in {"", "/", route.path, f"{route.path}/"}:
            await route.downstream.handle_streamable_http(scope, receive, send)
            return

        if method == "GET" and path in {"/sse", f"{route.path}/sse", f"{route.path}/sse/"}:
            await route.downstream.handle_sse(scope, receive, send)
            return

        if method == "POST" and path in {
            "/messages",
            "/messages/",
            f"{route.path}/messages",
            f"{route.path}/messages/",
        }:
            await route.downstream.handle_sse_post(scope, receive, send)
            return

        response = Response(status_code=404)
        await response(scope, receive, send)

    return mcp_transport_app
