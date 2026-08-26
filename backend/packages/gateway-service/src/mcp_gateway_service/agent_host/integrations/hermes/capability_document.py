"""Wire models for the Hermes API server capability document."""

from __future__ import annotations

from typing import Literal

from openai import BaseModel
from pydantic import ConfigDict


class HermesCapabilityDocumentModel(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)


class HermesAuthDescriptor(HermesCapabilityDocumentModel):
    type: str
    required: bool


class HermesRuntimeDescriptor(HermesCapabilityDocumentModel):
    mode: str
    tool_execution: str
    split_runtime: bool
    description: str | None = None


class HermesFeatureSet(HermesCapabilityDocumentModel):
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


class HermesEndpointDescriptor(HermesCapabilityDocumentModel):
    method: str
    path: str


class HermesCapabilityDocument(HermesCapabilityDocumentModel):
    object: Literal["hermes.api_server.capabilities"]
    platform: str
    model: str
    auth: HermesAuthDescriptor
    runtime: HermesRuntimeDescriptor
    features: HermesFeatureSet
    endpoints: dict[str, HermesEndpointDescriptor]
