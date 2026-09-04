"""Compose the optional Agent Host application and selected outbound integration.

Provider selection, deployment secrets, and managed adapter cleanup belong here. The Agent Host
application receives only its provider-neutral Target and runtime port.
"""

from __future__ import annotations

from dataclasses import dataclass

from mabrid.application.agent_host import (
    AgentEndpointAssignment,
    AgentHostService,
    AgentTarget,
    ManagedAgentRuntime,
)
from mabrid.application.agent_host.integrations.hermes import HermesChatCompletionsAdapter
from mabrid.application.gateway.sessions import GatewaySessionCoordinator

from mabrid.server.config import RuntimeConfiguration, RuntimeHermesAgentConfig
from mabrid.server.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class AgentHostComposition:
    service: AgentHostService
    runtime: ManagedAgentRuntime


async def compose_agent_host(
    configuration: RuntimeConfiguration,
    gateway: GatewaySessionCoordinator,
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
    runtime = _build_agent_runtime(config.runtime)
    try:
        target = AgentTarget(
            target_id=config.target_id,
            runtime_profile=runtime.profile,
            endpoint_assignment=AgentEndpointAssignment(endpoint_slug=config.endpoint_slug),
        )
        composition = AgentHostComposition(
            service=AgentHostService(target, runtime),
            runtime=runtime,
        )
    except BaseException:
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
