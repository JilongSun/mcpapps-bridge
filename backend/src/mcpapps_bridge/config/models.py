"""Typed YAML configuration models for the bridge runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    sqlite_path: Path = Path("backend/var/mcpapps-bridge.db")
    auto_migrate: bool = True
    bootstrap_mode: Literal["seed-if-empty"] = "seed-if-empty"


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
    upstream_session_mode: Literal["isolated", "shared"] = "isolated"
    lazy_upstream_connections: bool = True
    idle_timeout_seconds: float = 900.0
    enabled: bool = True


class McpAppsBridgeConfig(CamelModel):
    bridge: BridgeRuntimeConfig = Field(default_factory=BridgeRuntimeConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    upstreams: dict[str, UpstreamFileConfig] = Field(default_factory=dict)
    endpoints: dict[str, EndpointFileConfig] = Field(default_factory=dict)
    default_upstream: str | None = None

    @model_validator(mode="after")
    def validate_upstream_defaults(self) -> McpAppsBridgeConfig:
        if not self.upstreams:
            raise ValueError("configuration must define at least one upstream")
        if self.default_upstream is not None and self.default_upstream not in self.upstreams:
            raise ValueError(
                f"defaultUpstream '{self.default_upstream}' is not defined in upstreams"
            )
        for endpoint_name, endpoint in self.endpoints.items():
            for binding in endpoint.bindings:
                if binding.upstream not in self.upstreams:
                    raise ValueError(
                        f"endpoint '{endpoint_name}' references unknown upstream "
                        f"'{binding.upstream}'"
                    )
        return self
