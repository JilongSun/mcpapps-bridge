"""Immutable runtime plans consumed by bridge core."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, PositiveFloat, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EndpointMode(StrEnum):
    PASSTHROUGH = "passthrough"
    AGGREGATE = "aggregate"


class StdioUpstreamConfig(ContractModel):
    transport: Literal["stdio"] = "stdio"
    command: str = Field(min_length=1)
    args: tuple[str, ...] = ()
    cwd: Path | None = None
    env: dict[str, str] = Field(default_factory=dict)


class SseUpstreamConfig(ContractModel):
    transport: Literal["sse"] = "sse"
    url: AnyHttpUrl
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: PositiveFloat = 30.0


class StreamableHttpUpstreamConfig(ContractModel):
    transport: Literal["streamable-http"] = "streamable-http"
    url: AnyHttpUrl
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: PositiveFloat = 30.0


UpstreamConfig = Annotated[
    StdioUpstreamConfig | SseUpstreamConfig | StreamableHttpUpstreamConfig,
    Field(discriminator="transport"),
]


class BridgeCapabilities(ContractModel):
    tools: bool = False
    resources: bool = False


class BindingPlan(ContractModel):
    binding_key: str = Field(min_length=1)
    upstream_key: str = Field(min_length=1)
    namespace: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]*$")
    priority: int = 0
    upstream: UpstreamConfig


class EndpointPlan(ContractModel):
    endpoint_key: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    mode: EndpointMode
    bindings: tuple[BindingPlan, ...]
    capabilities: BridgeCapabilities

    @model_validator(mode="after")
    def validate_bindings(self) -> EndpointPlan:
        if self.mode is EndpointMode.PASSTHROUGH:
            if len(self.bindings) != 1:
                raise ValueError("passthrough plans require exactly one binding")
            if self.bindings[0].namespace is not None:
                raise ValueError("passthrough plan bindings cannot define a namespace")
            return self

        if not self.bindings:
            raise ValueError("aggregate plans require at least one binding")
        namespaces = [binding.namespace for binding in self.bindings]
        if any(namespace is None for namespace in namespaces):
            raise ValueError("aggregate plan bindings require namespaces")
        if len(namespaces) != len(set(namespaces)):
            raise ValueError("aggregate plan binding namespaces must be unique")
        return self
