"""Read-only product capabilities; remote Host status never changes local readiness."""

from typing import Literal

from fastapi import APIRouter, Response

from mabrid.application.agent_host import AgentHostCapabilityService, AgentHostCapabilitySnapshot

from .host_contracts import HostHttpModel


class GatewayCapabilities(HostHttpModel):
    enabled: Literal[True] = True
    topology_read: bool
    session_inspection: bool
    topology_mutation: Literal[False] = False
    mcp_apps_protocol_passthrough: Literal[True] = True


class ProductCapabilitiesResponse(HostHttpModel):
    gateway: GatewayCapabilities
    agent_host: AgentHostCapabilitySnapshot


def create_capabilities_router(
    service: AgentHostCapabilityService, *, management_enabled: bool
) -> APIRouter:
    router = APIRouter(tags=["Capabilities"])

    @router.get("/api/v1/capabilities", response_model=ProductCapabilitiesResponse)
    async def capabilities(response: Response) -> ProductCapabilitiesResponse:
        response.headers["Cache-Control"] = "no-store"
        return ProductCapabilitiesResponse(
            gateway=GatewayCapabilities(
                topology_read=management_enabled, session_inspection=management_enabled
            ),
            agent_host=await service.snapshot(),
        )

    return router
