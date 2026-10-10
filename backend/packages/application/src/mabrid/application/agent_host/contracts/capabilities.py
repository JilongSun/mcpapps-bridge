"""Provider-neutral, point-in-time evidence for selected runtime interfaces."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, Field

from .base import AgentHostModel


class RuntimeSupport(AgentHostModel):
    session_create: bool | None = None
    session_reopen: bool | None = None
    session_history: bool | None = None
    session_streaming: bool | None = None
    run_status: bool | None = None
    run_stop: bool | None = None
    compatibility_streaming: bool | None = None


class RuntimeCapabilityObservation(AgentHostModel):
    availability: Literal["available", "unavailable", "unknown"]
    reason: Literal[
        "discovery_verified",
        "discovery_unsupported",
        "invalid_response",
        "authentication_failed",
        "runtime_unavailable",
        "probe_timeout",
        "probe_failed",
    ]
    checked_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    support: RuntimeSupport = Field(default_factory=RuntimeSupport)


class EffectiveCapability(AgentHostModel):
    implemented: bool
    enabled: bool
    remote_support: bool | None = None
    availability: Literal["available", "unavailable", "unknown", "disabled", "unsupported"]
    reason: Literal[
        "local_available",
        "local_disabled",
        "not_implemented",
        "remote_verified",
        "remote_unknown",
        "remote_unsupported",
        "runtime_unavailable",
    ]


class AgentHostFeatures(AgentHostModel):
    session_list: EffectiveCapability
    session_create: EffectiveCapability
    session_reopen: EffectiveCapability
    session_history: EffectiveCapability
    session_streaming: EffectiveCapability
    run_cancel: EffectiveCapability
    run_reconcile: EffectiveCapability
    tool_activity: EffectiveCapability
    widgets: EffectiveCapability
    compatibility_streaming: EffectiveCapability
    host_actions: EffectiveCapability
    event_replay: EffectiveCapability
    remote_session_import: EffectiveCapability


class AgentHostCapabilitySnapshot(AgentHostModel):
    enabled: bool
    target_id: str | None = None
    native_runtime: RuntimeCapabilityObservation | None = None
    compatibility_runtime: RuntimeCapabilityObservation | None = None
    features: AgentHostFeatures
    max_concurrent_runs: Literal[1] = 1
