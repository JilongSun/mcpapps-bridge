"""FastAPI control plane for the early bridge runtime."""

from __future__ import annotations

from fastapi import FastAPI

from mcpapps_bridge.session import BridgeSessionState


def create_app(session_state: BridgeSessionState | None = None) -> FastAPI:
    app = FastAPI(title="mcpapps bridge", version="0.1.0")
    state = session_state or BridgeSessionState(session_id="local-dev-session")

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

    return app
