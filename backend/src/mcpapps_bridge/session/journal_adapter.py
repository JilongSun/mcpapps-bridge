"""Transitional application journal adapter for the current session store."""

from __future__ import annotations

from mcp_bridge_core import (
    BindingAvailabilityStatus,
    BridgeFailure,
    ToolCallResult as CoreToolCallResult,
)
from mcp_gateway_service import (
    BindingAvailabilityJournalEvent,
    ErrorRaisedJournalEvent,
    ResourceLoadedJournalEvent,
    SessionJournalEvent,
    SessionStartedJournalEvent,
    ToolCallCompletedJournalEvent,
    ToolCallStartedJournalEvent,
    ToolsPublishedJournalEvent,
)

from mcpapps_bridge.domain import EndpointTopologyRevision
from mcpapps_bridge.models import (
    AppResource,
    ToolCallResult,
    ToolDescriptor,
    UpstreamAvailability,
    UpstreamAvailabilityStatus,
    UpstreamInitialization,
)

from .protocol import BridgeSessionStore


class BridgeSessionStoreJournal:
    """Write application journal events through the pre-refactor store contract."""

    def __init__(
        self,
        session_key: str,
        revision: EndpointTopologyRevision,
        store: BridgeSessionStore,
    ) -> None:
        self._session_key = session_key
        self._store = store
        self._bindings = {
            str(binding.binding_revision_id): binding
            for binding in revision.bindings
            if binding.enabled
        }
        self._availability: dict[str, UpstreamAvailability] = {}

    async def append(self, event: SessionJournalEvent) -> None:
        if event.session_key != self._session_key:
            raise ValueError(
                f"journal session mismatch: {event.session_key} != {self._session_key}"
            )

        if isinstance(event, SessionStartedJournalEvent):
            await self._store.start(_identity(event.identity))
            return
        if isinstance(event, BindingAvailabilityJournalEvent):
            await self._record_availability(event)
            return
        if isinstance(event, ToolsPublishedJournalEvent):
            await self._store.register_tools(
                [ToolDescriptor.model_validate(tool.model_dump()) for tool in event.tools]
            )
            return
        if isinstance(event, ToolCallStartedJournalEvent):
            await self._store.start_tool_call(
                event.tool_name,
                event.arguments,
                call_id=event.operation_key,
            )
            return
        if isinstance(event, ToolCallCompletedJournalEvent):
            result = _tool_result(event.result, event.failure)
            await self._store.complete_tool_call(
                event.operation_key,
                result,
                failed=event.failure is not None or result.is_error,
            )
            return
        if isinstance(event, ResourceLoadedJournalEvent):
            await self._store.load_resource(AppResource.model_validate(event.resource.model_dump()))
            return
        if isinstance(event, ErrorRaisedJournalEvent):
            await self._store.record_error(
                event.failure.message,
                details={
                    "operation": event.operation,
                    "code": event.failure.code.value,
                    "retryable": event.failure.retryable,
                    **event.failure.details,
                },
            )
            return
        raise TypeError(f"Unsupported session journal event: {type(event).__name__}")

    async def _record_availability(self, event: BindingAvailabilityJournalEvent) -> None:
        binding = self._bindings.get(event.binding_key)
        if binding is None:
            raise KeyError(f"Unknown binding revision: {event.binding_key}")
        failure = event.failure
        self._availability[event.binding_key] = UpstreamAvailability(
            binding_revision_id=event.binding_key,
            namespace=binding.namespace,
            upstream_revision_id=str(binding.upstream.revision_id),
            upstream_server_id=str(binding.upstream.server_id),
            status=(
                UpstreamAvailabilityStatus.AVAILABLE
                if event.status is BindingAvailabilityStatus.AVAILABLE
                else (
                    UpstreamAvailabilityStatus.FAILED
                    if event.status is BindingAvailabilityStatus.FAILED
                    else UpstreamAvailabilityStatus.UNKNOWN
                )
            ),
            identity=_identity(event.identity) if event.identity is not None else None,
            failure_kind=failure.code.value if failure is not None else None,
            error_message=failure.message if failure is not None else None,
            updated_at=event.occurred_at,
        )
        await self._store.set_upstream_availability(list(self._availability.values()))


def _identity(identity: object) -> UpstreamInitialization:
    return UpstreamInitialization.model_validate(identity)


def _tool_result(
    result: CoreToolCallResult | None,
    failure: BridgeFailure | None,
) -> ToolCallResult:
    if result is not None:
        return ToolCallResult.model_validate(result.model_dump())
    if failure is None:
        raise ValueError("completed tool call requires a result or failure")
    return ToolCallResult(
        content=[{"type": "text", "text": failure.message}],
        is_error=True,
        metadata={
            "bridge/failure": {
                "code": failure.code.value,
                "retryable": failure.retryable,
                "details": failure.details,
            }
        },
    )
