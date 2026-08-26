"""Typed contract for the Hermes API server capability document."""

from __future__ import annotations

from typing import Literal

from openai import BaseModel
from pydantic import ConfigDict


class HermesCapabilityModel(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)


class HermesAuthCapabilities(HermesCapabilityModel):
    type: str
    required: bool


class HermesRuntimeCapabilities(HermesCapabilityModel):
    mode: str
    tool_execution: str
    split_runtime: bool
    description: str | None = None


class HermesFeatureCapabilities(HermesCapabilityModel):
    chat_completions: bool = False
    chat_completions_streaming: bool = False
    responses_api: bool = False
    responses_streaming: bool = False
    run_submission: bool = False
    run_status: bool = False
    run_events_sse: bool = False
    run_stop: bool = False
    run_steer: bool = False
    run_approval_response: bool = False
    tool_progress_events: bool = False
    approval_events: bool = False
    session_resources: bool = False
    session_chat: bool = False
    session_chat_streaming: bool = False
    session_continuity_header: str | None = None
    session_key_header: str | None = None


class HermesApiEndpoint(HermesCapabilityModel):
    method: str
    path: str


class HermesApiCapabilities(HermesCapabilityModel):
    object: Literal["hermes.api_server.capabilities"]
    platform: str
    model: str
    auth: HermesAuthCapabilities
    runtime: HermesRuntimeCapabilities
    features: HermesFeatureCapabilities
    endpoints: dict[str, HermesApiEndpoint]
