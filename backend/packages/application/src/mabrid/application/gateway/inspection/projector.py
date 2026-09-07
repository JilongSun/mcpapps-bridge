"""Project bridge-core observations into durable Gateway inspection state.

The projector is the application boundary between protocol facts and inspection records. It
performs explicit field mapping and does not introduce an intermediate journal event vocabulary.
"""

from __future__ import annotations

from mabrid.bridge import (
    BindingAvailabilityStatus,
    BindingAvailabilityChanged,
    BridgeErrorRaised,
    BridgeFailure,
    BridgeObservation,
    BridgeObserver,
    BridgeSessionStarted,
    ResourceRead,
    ToolCallCompleted,
    ToolCallResult as CoreToolCallResult,
    ToolCallStarted,
    ToolDescriptor as CoreToolDescriptor,
    ToolsPublished,
    UpstreamIdentity,
)

from .models import (
    ResourceContent,
    ResourceReadRecord,
    ToolCallResult,
    ToolDescriptor,
    UpstreamAvailability,
    UpstreamAvailabilityStatus,
    UpstreamInitialization,
)
from .ports import BridgeSessionStore
from ..topology.revisions import EndpointTopologyRevision


class SessionInspectionProjector(BridgeObserver):
    """Apply observations for one bridge session to its inspection store."""

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

    async def observe(self, event: BridgeObservation) -> None:
        if event.session_key != self._session_key:
            raise ValueError(
                f"observation session mismatch: {event.session_key} != {self._session_key}"
            )

        if isinstance(event, BridgeSessionStarted):
            await self._store.start(_identity(event.identity))
            return
        if isinstance(event, BindingAvailabilityChanged):
            await self._record_availability(event)
            return
        if isinstance(event, ToolsPublished):
            await self._store.register_tools([_tool_descriptor(tool) for tool in event.tools])
            return
        if isinstance(event, ToolCallStarted):
            await self._store.start_tool_call(
                event.tool_name,
                event.arguments,
                call_id=event.operation_key,
            )
            return
        if isinstance(event, ToolCallCompleted):
            result = _tool_result(event.result, event.failure)
            await self._store.complete_tool_call(
                event.operation_key,
                result,
                failed=event.failure is not None or result.is_error,
            )
            return
        if isinstance(event, ResourceRead):
            await self._store.record_resource_read(
                ResourceReadRecord(
                    requested_uri=event.requested_uri,
                    contents=[
                        ResourceContent(
                            uri=content.uri,
                            mime_type=content.mime_type,
                            text=content.text,
                            blob=content.blob,
                            metadata=content.metadata,
                        )
                        for content in event.result.contents
                    ],
                    metadata=event.result.metadata,
                    loaded_at=event.observed_at,
                )
            )
            return
        if isinstance(event, BridgeErrorRaised):
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
        raise TypeError(f"Unsupported bridge observation: {type(event).__name__}")

    async def _record_availability(self, event: BindingAvailabilityChanged) -> None:
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
            updated_at=event.observed_at,
        )
        await self._store.set_upstream_availability(list(self._availability.values()))


def _identity(identity: UpstreamIdentity) -> UpstreamInitialization:
    return UpstreamInitialization(
        server_name=identity.server_name,
        server_version=identity.server_version,
        protocol_version=identity.protocol_version,
        instructions=identity.instructions,
        supports_tools=identity.supports_tools,
        supports_resources=identity.supports_resources,
        raw_capabilities=dict(identity.raw_capabilities),
    )


def _tool_descriptor(tool: CoreToolDescriptor) -> ToolDescriptor:
    return ToolDescriptor(
        name=tool.name,
        title=tool.title,
        description=tool.description,
        input_schema=dict(tool.input_schema),
        output_schema=dict(tool.output_schema) if tool.output_schema is not None else None,
        annotations=dict(tool.annotations),
        ui_resource_uri=tool.ui_resource_uri,
        metadata=dict(tool.metadata),
    )


def _tool_result(
    result: CoreToolCallResult | None,
    failure: BridgeFailure | None,
) -> ToolCallResult:
    if result is not None:
        return ToolCallResult(
            content=[dict(item) for item in result.content],
            structured_content=(
                dict(result.structured_content) if result.structured_content is not None else None
            ),
            is_error=result.is_error,
            metadata=dict(result.metadata),
        )
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
