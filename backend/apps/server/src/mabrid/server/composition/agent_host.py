"""Compose the optional Agent Host application and selected outbound integration.

Provider selection, deployment secrets, and managed adapter cleanup belong here. The Agent Host
application receives only its provider-neutral Target and runtime port.
"""

from __future__ import annotations

from dataclasses import dataclass
import anyio
from typing import Literal
from uuid import UUID

from mabrid.application.agent_host import (
    AgentEndpointAssignment,
    AgentHostService,
    AgentSessionService,
    AgentTarget,
    InMemoryOperationRunAttributionRegistry,
    ManagedAgentRuntime,
)
from mabrid.application.agent_host.integrations.hermes import (
    HermesChatCompletionsAdapter,
    HermesSessionAdapter,
)
from mabrid.application.host import (
    HostCapabilityComposition,
    HostObservationFactory,
    NativeSessionPorts,
    compose_host_capabilities,
)
from mabrid.application.gateway.sessions import GatewaySessionCoordinator

from mabrid.server.config import (
    RuntimeConfiguration,
    RuntimeHermesAgentConfig,
    build_advertised_mcp_url,
)
from mabrid.server.logging import get_logger
from mabrid.server.persistence import SqliteDatabase
from mabrid.server.persistence.agent_host import SqliteAgentSessionRepository

logger = get_logger(__name__)


@dataclass(frozen=True)
class AgentHostManagementView:
    target: AgentTarget
    endpoint_id: UUID
    endpoint_slug: str
    endpoint_path: str
    transport: Literal["streamable-http"]
    advertised_url: str


@dataclass(frozen=True)
class AgentHostComposition:
    service: AgentHostService
    runtime: ManagedAgentRuntime
    management: AgentHostManagementView
    operation_attributions: InMemoryOperationRunAttributionRegistry
    bridge_observer_factory: HostObservationFactory
    capabilities: HostCapabilityComposition
    sessions: AgentSessionService | None
    session_runtime: HermesSessionAdapter | None

    async def close(self) -> None:
        with anyio.CancelScope(shield=True):
            try:
                if self.session_runtime is not None:
                    await self.session_runtime.close()
            finally:
                await self.runtime.close()


async def compose_agent_host(
    configuration: RuntimeConfiguration,
    gateway: GatewaySessionCoordinator,
    database: SqliteDatabase,
) -> AgentHostComposition | None:
    config = configuration.agent_host
    if not config.enabled:
        return None
    if config.target_id is None:
        raise ValueError("Enabled Agent Host configuration has no target ID")
    if config.endpoint_slug is None:
        raise ValueError("Enabled Agent Host configuration has no endpoint assignment")
    endpoint = gateway.resolve_published_endpoint(config.endpoint_slug)
    if endpoint is None:
        raise ValueError(
            f"Agent Target '{config.target_id}' references endpoint "
            f"'{config.endpoint_slug}', which is not published and enabled"
        )
    advertised_base_url = configuration.bridge.advertised_base_url
    if advertised_base_url is None:
        raise ValueError("Enabled Agent Host configuration has no advertised base URL")
    runtime = _build_agent_runtime(config.runtime)
    session_runtime: HermesSessionAdapter | None = None
    try:
        target = AgentTarget(
            target_id=config.target_id,
            runtime_profile=runtime.profile,
            endpoint_assignment=AgentEndpointAssignment(endpoint_slug=config.endpoint_slug),
        )
        native: NativeSessionPorts | None = None
        if config.runtime.sessions is not None:
            if config.runtime.api_key is None:
                raise ValueError("Enabled Agent Host configuration has no Hermes API key")
            session_runtime = HermesSessionAdapter(
                api_root=config.runtime.sessions.api_root,
                api_key=config.runtime.api_key.get_secret_value(),
                runtime_binding_id=config.runtime.sessions.binding_id,
                timeout_seconds=config.runtime.timeout_seconds,
            )
            native = NativeSessionPorts(
                binding_id=config.runtime.sessions.binding_id,
                catalog=session_runtime,
                history=session_runtime,
                execution=session_runtime,
                control=session_runtime,
            )
        capabilities = await compose_host_capabilities(
            target,
            runtime,
            SqliteAgentSessionRepository(database.session_factory),
            native=native,
            mcp_apps_enabled=config.mcp_apps_enabled,
        )
        composition = AgentHostComposition(
            service=capabilities.agent_host,
            runtime=runtime,
            management=AgentHostManagementView(
                target=target,
                endpoint_id=endpoint.revision.endpoint_id,
                endpoint_slug=endpoint.revision.slug,
                endpoint_path=endpoint.path,
                transport="streamable-http",
                advertised_url=build_advertised_mcp_url(
                    advertised_base_url,
                    endpoint.revision.slug,
                ),
            ),
            operation_attributions=capabilities.attributions,
            bridge_observer_factory=capabilities.bridge_observer_factory,
            capabilities=capabilities,
            sessions=capabilities.sessions,
            session_runtime=session_runtime,
        )
    except BaseException:
        with anyio.CancelScope(shield=True):
            try:
                if session_runtime is not None:
                    await session_runtime.close()
            finally:
                await runtime.close()
        raise
    logger.info(
        "Agent Target enabled: id=%s integration=%s endpoint=%s runtime_url=%s",
        target.target_id,
        target.runtime_profile.integration_kind,
        endpoint.path,
        config.runtime.base_url,
    )
    return composition


def _build_agent_runtime(config: RuntimeHermesAgentConfig) -> ManagedAgentRuntime:
    if config.integration != "hermes":
        raise ValueError(f"Unsupported Agent Runtime integration: {config.integration}")
    if config.interface != "openai-chat-completions":
        raise ValueError(f"Unsupported Hermes runtime interface: {config.interface}")
    if config.api_key is None:
        raise ValueError("Enabled Agent Host configuration has no Hermes API key")
    return HermesChatCompletionsAdapter(
        base_url=config.base_url,
        api_key=config.api_key.get_secret_value(),
        timeout_seconds=config.timeout_seconds,
    )
