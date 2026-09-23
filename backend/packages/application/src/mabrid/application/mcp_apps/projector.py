"""Project correlated Gateway observations into MCP Apps widget lifecycle events."""

from __future__ import annotations

from dataclasses import dataclass

from mabrid.bridge import (
    BridgeErrorRaised,
    BridgeObservation,
    ResourceRead,
    ToolCallCompleted,
    ToolCallResult,
    ToolCallStarted,
    ToolsPublished,
)

from .contracts import (
    ApplicationResourceContent,
    WidgetCreated,
    WidgetFailed,
    WidgetInstance,
    WidgetToolResult,
)
from ..agent_host import OperationRunAttribution
from .ports import OperationAttributionReader, WidgetEventStore


@dataclass(frozen=True)
class _PendingToolOperation:
    tool_name: str
    application_resource_uri: str | None
    attribution: OperationRunAttribution
    result: ToolCallResult | None = None


class McpAppsLifecycleProjector:
    def __init__(
        self,
        session_key: str,
        attributions: OperationAttributionReader,
        events: WidgetEventStore,
    ) -> None:
        self._session_key = session_key
        self._attributions = attributions
        self._events = events
        self._application_resources_by_tool: dict[str, str] = {}
        self._operations: dict[str, _PendingToolOperation] = {}

    async def observe(self, event: BridgeObservation) -> None:
        if event.session_key != self._session_key:
            raise ValueError(
                f"observation session mismatch: {event.session_key} != {self._session_key}"
            )
        if isinstance(event, ToolsPublished):
            self._application_resources_by_tool = {
                tool.name: tool.ui_resource_uri
                for tool in event.tools
                if tool.ui_resource_uri is not None
            }
            return
        if isinstance(event, ToolCallStarted):
            application_resource_uri = self._application_resources_by_tool.get(event.tool_name)
            if application_resource_uri is not None:
                attribution = await self._attributions.get(
                    self._session_key,
                    event.operation_key,
                )
                if attribution is None:
                    return
                self._operations[event.operation_key] = _PendingToolOperation(
                    tool_name=event.tool_name,
                    application_resource_uri=application_resource_uri,
                    attribution=attribution,
                )
                await self._events.start_operation(attribution)
            return
        if isinstance(event, ToolCallCompleted):
            operation = self._operations.get(event.operation_key)
            if operation is None:
                return
            if event.result is None or event.failure is not None:
                del self._operations[event.operation_key]
                await self._events.settle_operation(operation.attribution)
                return
            self._operations[event.operation_key] = _PendingToolOperation(
                tool_name=operation.tool_name,
                application_resource_uri=operation.application_resource_uri,
                attribution=operation.attribution,
                result=event.result,
            )
            return
        if isinstance(event, ResourceRead) and event.operation_key is not None:
            await self._create_widget(event)
            return
        if (
            isinstance(event, BridgeErrorRaised)
            and event.operation == "application_resource_load"
            and event.operation_key is not None
        ):
            await self._fail_widget(event)

    async def _create_widget(self, event: ResourceRead) -> None:
        operation_key = event.operation_key
        if operation_key is None:
            return
        operation = self._completed_operation(operation_key)
        if operation is None:
            self._operations.pop(operation_key, None)
            return
        attribution = operation.attribution
        await self._events.append(
            WidgetCreated(
                widget=WidgetInstance(
                    run_id=attribution.run_id,
                    target_id=attribution.target_id,
                    session_key=event.session_key,
                    operation_key=operation_key,
                    tool_name=operation.tool_name,
                    tool_result=_tool_result(operation.result),
                    application_resource_uri=event.requested_uri,
                    resource_contents=tuple(
                        ApplicationResourceContent(
                            uri=content.uri,
                            mime_type=content.mime_type,
                            text=content.text,
                            blob=content.blob,
                            metadata=content.metadata,
                        )
                        for content in event.result.contents
                    ),
                    resource_metadata=event.result.metadata,
                )
            )
        )
        del self._operations[operation_key]

    async def _fail_widget(self, event: BridgeErrorRaised) -> None:
        operation_key = event.operation_key
        if operation_key is None:
            return
        operation = self._completed_operation(operation_key)
        if operation is None:
            self._operations.pop(operation_key, None)
            return
        attribution = operation.attribution
        resource_uri = operation.application_resource_uri
        if resource_uri is None:
            return
        await self._events.append(
            WidgetFailed(
                run_id=attribution.run_id,
                target_id=attribution.target_id,
                session_key=event.session_key,
                operation_key=operation_key,
                tool_name=operation.tool_name,
                tool_result=_tool_result(operation.result),
                application_resource_uri=resource_uri,
                error_message=event.failure.message,
            )
        )
        del self._operations[operation_key]

    def _completed_operation(self, operation_key: str) -> _PendingToolOperation | None:
        operation = self._operations.get(operation_key)
        if operation is None or operation.result is None:
            return None
        return operation


def _tool_result(result: ToolCallResult | None) -> WidgetToolResult:
    if result is None:
        raise ValueError("Completed widget operation has no tool result")
    return WidgetToolResult(
        content=result.content,
        structured_content=result.structured_content,
        is_error=result.is_error,
        metadata=result.metadata,
    )
