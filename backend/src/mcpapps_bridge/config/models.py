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
    session_id: str = "local-dev-session"
    proxy_name: str | None = None
    httpx_timeout_seconds: float | None = None


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


class McpAppsBridgeConfig(CamelModel):
    bridge: BridgeRuntimeConfig = Field(default_factory=BridgeRuntimeConfig)
    upstreams: dict[str, UpstreamFileConfig] = Field(default_factory=dict)
    default_upstream: str | None = None

    @model_validator(mode="after")
    def validate_upstream_defaults(self) -> McpAppsBridgeConfig:
        if not self.upstreams:
            raise ValueError("configuration must define at least one upstream")
        if self.default_upstream is not None and self.default_upstream not in self.upstreams:
            raise ValueError(
                f"defaultUpstream '{self.default_upstream}' is not defined in upstreams"
            )
        return self
