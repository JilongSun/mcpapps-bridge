"""FastAPI control plane for the early bridge runtime."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from starlette.routing import Mount

from mcpapps_bridge.mcp import BridgeProxyServer
from mcpapps_bridge.session import BridgeSessionState


def create_app(
    session_state: BridgeSessionState | None = None,
    proxy_server: BridgeProxyServer | None = None,
) -> FastAPI:
    state = session_state or BridgeSessionState(session_id="local-dev-session")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if proxy_server is not None:
            await proxy_server.start()
        try:
            yield
        finally:
            if proxy_server is not None:
                await proxy_server.close()

    app = FastAPI(title="mcpapps bridge", version="0.1.0", lifespan=lifespan)
    app.state.session_state = state
    app.state.proxy_server = proxy_server

    if proxy_server is not None:

        async def sse_endpoint(request: Request) -> Response:
            return await proxy_server.handle_sse(request.scope, request.receive, request._send)  # type: ignore[reportPrivateUsage]

        app.add_api_route("/mcp/sse", sse_endpoint, methods=["GET"], include_in_schema=False)
        app.router.routes.append(Mount("/mcp/messages", app=proxy_server.handle_sse_post))

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
