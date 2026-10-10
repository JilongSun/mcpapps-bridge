"""Wire models for the Hermes API server capability document."""

from __future__ import annotations

from typing import Literal

from openai import BaseModel
from pydantic import ConfigDict

from ...contracts.capabilities import RuntimeCapabilityObservation, RuntimeSupport


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


def capability_observation(document: HermesCapabilityDocument) -> RuntimeCapabilityObservation:
    def declared(feature: str, endpoint: str, method: str, path: str) -> bool | None:
        if feature not in document.features.model_fields_set:
            return None
        if getattr(document.features, feature) is False:
            return False
        descriptor = document.endpoints.get(endpoint)
        if descriptor is None or (descriptor.method, descriptor.path) != (method, path):
            return None
        return True

    return RuntimeCapabilityObservation(
        availability="available",
        reason="discovery_verified",
        support=RuntimeSupport(
            session_create=declared("session_resources", "session_create", "POST", "/api/sessions"),
            session_reopen=declared(
                "session_resources", "session", "GET", "/api/sessions/{session_id}"
            ),
            session_history=declared(
                "session_resources",
                "session_messages",
                "GET",
                "/api/sessions/{session_id}/messages",
            ),
            session_streaming=declared(
                "session_chat_streaming",
                "session_chat_stream",
                "POST",
                "/api/sessions/{session_id}/chat/stream",
            ),
            run_status=declared("run_status", "run_status", "GET", "/v1/runs/{run_id}"),
            run_stop=declared("run_stop", "run_stop", "POST", "/v1/runs/{run_id}/stop"),
            compatibility_streaming=declared(
                "chat_completions_streaming", "chat_completions", "POST", "/v1/chat/completions"
            ),
        ),
    )


def capability_http_failure(status: int) -> RuntimeCapabilityObservation:
    if status in {404, 405, 501}:
        return RuntimeCapabilityObservation(availability="unknown", reason="discovery_unsupported")
    return RuntimeCapabilityObservation(
        availability="unavailable",
        reason="authentication_failed" if status in {401, 403} else "runtime_unavailable",
    )
