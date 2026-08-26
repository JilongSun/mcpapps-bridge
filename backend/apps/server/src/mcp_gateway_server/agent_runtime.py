"""Deployment composition for outbound Agent Runtime integrations."""

from mcp_gateway_service import ManagedAgentRuntime
from mcp_gateway_service.agent_host.integrations.hermes import HermesChatCompletionsAdapter

from mcp_gateway_server.config import RuntimeHermesAgentConfig


def build_agent_runtime(config: RuntimeHermesAgentConfig) -> ManagedAgentRuntime:
    if config.integration == "hermes":
        if config.interface != "openai-chat-completions":
            raise ValueError(f"Unsupported Hermes runtime interface: {config.interface}")
        if config.api_key is None:
            raise ValueError("Enabled Agent Host configuration has no Hermes API key")
        return HermesChatCompletionsAdapter(
            base_url=config.base_url,
            api_key=config.api_key.get_secret_value(),
            timeout_seconds=config.timeout_seconds,
        )
    raise ValueError(f"Unsupported Agent Runtime integration: {config.integration}")
