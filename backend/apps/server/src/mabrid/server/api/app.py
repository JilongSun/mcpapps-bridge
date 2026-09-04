"""Composition root for inbound HTTP surfaces."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mabrid.bridge import create_mcp_asgi_app
from mabrid.application.agent_host import AgentHostService
from mabrid.application.gateway.sessions import GatewaySessionCoordinator
from mabrid.application.gateway import GatewayMcpSessionBroker

from mabrid.server.api.openai_compat import create_openai_compatibility_router
from mabrid.server.logging import get_logger

logger = get_logger(__name__)


def create_app(
    manager: GatewaySessionCoordinator,
    *,
    agent_host: AgentHostService | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logger.info("FastAPI application starting (lifespan enter)")
        async with manager.lifecycle():
            yield
        logger.info("FastAPI application shutting down (lifespan exit)")

    app = FastAPI(title="Mabrid", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["mcp-session-id"],
    )
    app.state.gateway = manager

    app.mount("/mcp", create_mcp_asgi_app(GatewayMcpSessionBroker(manager)))
    if agent_host is not None:
        app.include_router(create_openai_compatibility_router(agent_host))

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
