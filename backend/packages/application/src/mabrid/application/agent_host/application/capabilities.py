"""Bounded, request-scoped capability reporting; never controls Gateway readiness."""

import anyio

from ..contracts.capabilities import (
    AgentHostCapabilitySnapshot,
    AgentHostFeatures,
    EffectiveCapability,
    RuntimeCapabilityObservation,
)
from .ports import RuntimeCapabilityProbe


def _support(*values: bool | None) -> bool | None:
    if any(value is False for value in values):
        return False
    return None if any(value is None for value in values) else True


def _effective(
    *,
    enabled: bool,
    observation: RuntimeCapabilityObservation | None = None,
    support: bool | None = None,
    remote: bool = True,
    implemented: bool = True,
) -> EffectiveCapability:
    if not implemented:
        availability, reason = "unsupported", "not_implemented"
    elif not enabled:
        availability, reason = "disabled", "local_disabled"
    elif not remote:
        availability, reason = "available", "local_available"
    elif support is False:
        availability, reason = "unsupported", "remote_unsupported"
    elif observation is not None and observation.availability == "unavailable":
        availability, reason = "unavailable", "runtime_unavailable"
    elif observation is None or observation.availability == "unknown" or support is None:
        availability, reason = "unknown", "remote_unknown"
    else:
        availability, reason = "available", "remote_verified"
    return EffectiveCapability.model_validate(
        {
            "implemented": implemented,
            "enabled": enabled and implemented,
            "remote_support": support if remote else None,
            "availability": availability,
            "reason": reason,
        }
    )


class AgentHostCapabilityService:
    def __init__(
        self,
        *,
        target_id: str | None = None,
        native_probe: RuntimeCapabilityProbe | None = None,
        compatibility_probe: RuntimeCapabilityProbe | None = None,
        native_enabled: bool | None = None,
        compatibility_enabled: bool | None = None,
        mcp_apps_enabled: bool = False,
        probe_timeout_seconds: float = 3.0,
    ) -> None:
        if probe_timeout_seconds <= 0:
            raise ValueError("Capability probe timeout must be positive")
        self._target_id = target_id
        self._native_probe = native_probe
        self._compatibility_probe = compatibility_probe
        self._native_enabled = (
            native_probe is not None if native_enabled is None else native_enabled
        )
        self._compatibility_enabled = (
            compatibility_probe is not None
            if compatibility_enabled is None
            else compatibility_enabled
        )
        self._mcp_apps_enabled = mcp_apps_enabled
        self._probe_timeout = probe_timeout_seconds

    async def _observe(self, probe: RuntimeCapabilityProbe) -> RuntimeCapabilityObservation:
        try:
            with anyio.fail_after(self._probe_timeout):
                return await probe.inspect_capabilities()
        except TimeoutError:
            return RuntimeCapabilityObservation(availability="unavailable", reason="probe_timeout")
        except Exception:
            return RuntimeCapabilityObservation(availability="unknown", reason="probe_failed")

    async def snapshot(self) -> AgentHostCapabilitySnapshot:
        native: RuntimeCapabilityObservation | None = None
        compatibility: RuntimeCapabilityObservation | None = None
        enabled = self._target_id is not None

        async def inspect_native() -> None:
            nonlocal native
            if enabled and self._native_enabled and self._native_probe is not None:
                native = await self._observe(self._native_probe)

        async def inspect_compatibility() -> None:
            nonlocal compatibility
            if enabled and self._compatibility_enabled and self._compatibility_probe is not None:
                compatibility = await self._observe(self._compatibility_probe)

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(inspect_native)
            tasks.start_soon(inspect_compatibility)
        native_enabled = enabled and self._native_enabled
        streaming = (
            _support(native.support.session_reopen, native.support.session_streaming)
            if native
            else None
        )

        def native_feature(
            support: bool | None, *, selected: bool = native_enabled
        ) -> EffectiveCapability:
            return _effective(enabled=selected, observation=native, support=support)

        unsupported = _effective(enabled=False, implemented=False)
        return AgentHostCapabilitySnapshot(
            enabled=enabled,
            target_id=self._target_id,
            native_runtime=native,
            compatibility_runtime=compatibility,
            features=AgentHostFeatures(
                session_list=_effective(enabled=native_enabled, remote=False),
                session_create=native_feature(native.support.session_create if native else None),
                session_reopen=native_feature(native.support.session_reopen if native else None),
                session_history=native_feature(
                    _support(native.support.session_reopen, native.support.session_history)
                    if native
                    else None
                ),
                session_streaming=native_feature(streaming),
                run_cancel=native_feature(
                    _support(native.support.run_stop, native.support.run_status) if native else None
                ),
                run_reconcile=native_feature(native.support.run_status if native else None),
                tool_activity=native_feature(streaming),
                widgets=native_feature(
                    streaming, selected=native_enabled and self._mcp_apps_enabled
                ),
                compatibility_streaming=_effective(
                    enabled=enabled and self._compatibility_enabled,
                    observation=compatibility,
                    support=compatibility.support.compatibility_streaming
                    if compatibility
                    else None,
                ),
                host_actions=unsupported,
                event_replay=unsupported,
                remote_session_import=unsupported,
            ),
        )
