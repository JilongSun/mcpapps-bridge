"""FastAPI control plane for the early bridge runtime."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from mcpapps_bridge.mcp import BridgeProxyServer
from mcpapps_bridge.session import BridgeSessionState


def create_app(
    session_state: BridgeSessionState | None = None,
    proxy_server: BridgeProxyServer | None = None,
) -> FastAPI:
    state = session_state or BridgeSessionState(session_id="local-dev-session")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if proxy_server is None:
            yield
            return

        await proxy_server.start()
        try:
            async with proxy_server.run_http_transports():
                yield
        finally:
            await proxy_server.close()

    app = FastAPI(title="mcpapps bridge", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:6274", "http://127.0.0.1:6274"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.state.session_state = state
    app.state.proxy_server = proxy_server

    if proxy_server is not None:

        async def mcp_transport_app(scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] != "http":
                response = Response(status_code=404)
                await response(scope, receive, send)
                return

            path = scope.get("path", "")
            method = scope.get("method", "GET")

            if method in {"GET", "POST", "DELETE"} and path in {"", "/", "/mcp", "/mcp/"}:
                await proxy_server.handle_streamable_http(scope, receive, send)
                return

            if method == "GET" and path in {"/sse", "/mcp/sse", "/mcp/sse/"}:
                await proxy_server.handle_sse(scope, receive, send)
                return

            if method == "POST" and path in {
                "/messages",
                "/messages/",
                "/mcp/messages",
                "/mcp/messages/",
            }:
                await proxy_server.handle_sse_post(scope, receive, send)
                return

            response = Response(status_code=404)
            await response(scope, receive, send)

        app.router.routes.append(Mount("/mcp", app=mcp_transport_app))

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
