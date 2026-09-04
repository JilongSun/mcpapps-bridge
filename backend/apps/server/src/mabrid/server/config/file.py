"""Validated YAML contracts for a Mabrid server deployment.

These models preserve camelCase file syntax and reject unknown fields. They contain environment
variable names but never resolved secrets or process-local absolute paths.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, PositiveFloat, model_validator


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class BridgeRuntimeConfig(CamelModel):
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    proxy_name: str | None = None
    httpx_timeout_seconds: float | None = None


class StorageConfig(CamelModel):
    sqlite_path: Path = Path("backend/var/mabrid.db")
    auto_migrate: bool = True


class HermesAgentRuntimeFileConfig(CamelModel):
    integration: Literal["hermes"] = "hermes"
    interface: Literal["openai-chat-completions"] = "openai-chat-completions"
    base_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8642/v1")
    api_key_env: str = Field(default="API_SERVER_KEY", min_length=1)
    timeout_seconds: PositiveFloat = 120.0


class AgentHostFileConfig(CamelModel):
    enabled: bool = False
    target_id: str | None = Field(default=None, min_length=1)
    endpoint_slug: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]*$")
    runtime: HermesAgentRuntimeFileConfig = Field(default_factory=HermesAgentRuntimeFileConfig)

    @model_validator(mode="after")
    def validate_enabled_target(self) -> AgentHostFileConfig:
        if self.enabled and self.target_id is None:
            raise ValueError("enabled Agent Host requires 'targetId'")
        if self.enabled and self.endpoint_slug is None:
            raise ValueError("enabled Agent Host requires 'endpointSlug'")
        return self


class UpstreamFileConfig(CamelModel):
    transport: Literal["stdio", "sse", "streamable-http"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: Path | None = None
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_transport_requirements(self) -> UpstreamFileConfig:
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio upstreams require 'command'")
        if self.transport in {"sse", "streamable-http"} and not self.url:
            raise ValueError(f"{self.transport} upstreams require 'url'")
        return self


class EndpointBindingFileConfig(CamelModel):
    upstream: str
    namespace: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]*$")
    priority: int = 0
    enabled: bool = True


class EndpointFileConfig(CamelModel):
    display_name: str | None = None
    mode: Literal["passthrough", "aggregate"] = "passthrough"
    bindings: list[EndpointBindingFileConfig]
    enabled: bool = True


class MabridConfig(CamelModel):
    bridge: BridgeRuntimeConfig = Field(default_factory=BridgeRuntimeConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    agent_host: AgentHostFileConfig = Field(default_factory=AgentHostFileConfig)
    upstreams: dict[str, UpstreamFileConfig] = Field(min_length=1)
    endpoints: dict[str, EndpointFileConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_upstream_defaults(self) -> MabridConfig:
        for endpoint_name, endpoint in self.endpoints.items():
            for binding in endpoint.bindings:
                if binding.upstream not in self.upstreams:
                    raise ValueError(
                        f"endpoint '{endpoint_name}' references unknown upstream "
                        f"'{binding.upstream}'"
                    )
        return self
