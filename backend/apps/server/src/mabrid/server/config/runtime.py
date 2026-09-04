"""Process-ready configuration resolved from file values and the environment.

Runtime configuration may contain resolved secrets and absolute local paths. It belongs only to
the deployable server and never crosses into bridge or application package contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, PositiveFloat, SecretStr

from .file import BridgeRuntimeConfig, EndpointFileConfig, StorageConfig


class RuntimeHermesAgentConfig(BaseModel):
    integration: Literal["hermes"] = "hermes"
    interface: Literal["openai-chat-completions"] = "openai-chat-completions"
    base_url: str = "http://127.0.0.1:8642/v1"
    api_key: SecretStr | None = None
    timeout_seconds: PositiveFloat = 120.0


class RuntimeAgentHostConfig(BaseModel):
    enabled: bool = False
    target_id: str | None = Field(default=None, min_length=1)
    endpoint_slug: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]*$")
    runtime: RuntimeHermesAgentConfig = Field(default_factory=RuntimeHermesAgentConfig)


class RuntimeUpstreamConfig(BaseModel):
    transport: Literal["stdio", "sse", "streamable-http"] = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: Path | None = None
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    httpx_timeout_seconds: float | None = None


@dataclass(frozen=True)
class RuntimeConfiguration:
    config_path: Path
    bridge: BridgeRuntimeConfig
    storage: StorageConfig
    upstreams: dict[str, RuntimeUpstreamConfig]
    endpoints: dict[str, EndpointFileConfig]
    diagnostic_upstream: str | None
    agent_host: RuntimeAgentHostConfig = field(default_factory=RuntimeAgentHostConfig)
