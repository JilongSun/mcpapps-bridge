"""Local process readiness HTTP route."""

from __future__ import annotations

from fastapi import APIRouter

from mabrid.server.composition import GatewayManagementComposition
from mabrid.server.logging import get_logger

from .management.dto import ReadinessResponse
from .management.errors import ManagementProblem, problem

logger = get_logger(__name__)


def create_readiness_router(management: GatewayManagementComposition) -> APIRouter:
    router = APIRouter(tags=["readiness"])

    @router.get("/ready", response_model=ReadinessResponse)
    async def ready() -> ReadinessResponse:
        if not management.published_endpoint_slugs:
            raise ManagementProblem(
                problem(
                    code="not_ready",
                    title="Service not ready",
                    status=503,
                    detail="No Gateway endpoint is published for this process.",
                )
            )
        try:
            persistence_ready = await management.readiness_probe.is_ready()
        except Exception:
            logger.exception("Readiness persistence probe failed")
            persistence_ready = False
        if not persistence_ready:
            raise ManagementProblem(
                problem(
                    code="persistence_unavailable",
                    title="Persistence unavailable",
                    status=503,
                    detail="SQLite persistence is unavailable.",
                )
            )
        return ReadinessResponse()

    return router
