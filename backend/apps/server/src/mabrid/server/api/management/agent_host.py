"""Read-only Agent Host management HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter

from mabrid.server.composition import AgentHostManagementView

from .dto import AgentTargetResponse
from .errors import ManagementProblem, problem


def create_agent_host_management_router(
    management: AgentHostManagementView | None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/agent-host", tags=["agent-host-management"])

    @router.get("/target", response_model=AgentTargetResponse)
    async def get_target() -> AgentTargetResponse:
        if management is None:
            raise ManagementProblem(
                problem(
                    code="agent_host_disabled",
                    title="Agent Host disabled",
                    status=404,
                    detail="The Agent Host is not enabled for this deployment.",
                )
            )
        return AgentTargetResponse.from_view(management)

    return router
