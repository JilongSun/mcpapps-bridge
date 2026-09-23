from __future__ import annotations

from uuid import uuid4

from mabrid.bridge import (
    BridgeErrorRaised,
    BridgeFailure,
    BridgeFailureCode,
    ReadResourceResult,
    ResourceContent,
    ResourceRead,
    ToolCallCompleted,
    ToolCallResult,
    ToolCallStarted,
    ToolDescriptor,
    ToolsPublished,
)
from mabrid.application.agent_host import OperationRunAttribution
from mabrid.application.agent_host import (
    AgentEndpointAssignment,
    AgentOperationAttributionObserverFactory,
    AgentRunCoordinator,
    AgentRuntimeInterface,
    AgentRuntimeProfile,
    AgentTarget,
    InMemoryOperationRunAttributionRegistry,
)
from mabrid.application.gateway.sessions import CompositeBridgeSessionObserverFactory
from mabrid.application.mcp_apps import (
    InMemoryWidgetEventStore,
    McpAppsLifecycleObserverFactory,
    McpAppsLifecycleProjector,
    WidgetCreated,
    WidgetFailed,
)


class AttributionReader:
    def __init__(self, attribution: OperationRunAttribution | None) -> None:
        self.attribution = attribution

    async def get(
        self,
        session_key: str,
        operation_key: str,
    ) -> OperationRunAttribution | None:
        attribution = self.attribution
        if (
            attribution is not None
            and attribution.session_key == session_key
            and attribution.operation_key == operation_key
        ):
            return attribution
        return None


async def _observe_completed_tool_operation(projector: McpAppsLifecycleProjector) -> None:
    await projector.observe(
        ToolsPublished(
            session_key="session-1",
            tools=(
                ToolDescriptor(
                    name="inspect",
                    ui_resource_uri="ui://fixture/inspect",
                ),
            ),
        )
    )
    await projector.observe(
        ToolCallStarted(
            session_key="session-1",
            operation_key="operation-1",
            tool_name="inspect",
        )
    )
    await projector.observe(
        ToolCallCompleted(
            session_key="session-1",
            operation_key="operation-1",
            result=ToolCallResult(
                content=({"type": "text", "text": "completed"},),
                structured_content={"value": 42},
            ),
        )
    )


def _attribution() -> OperationRunAttribution:
    return OperationRunAttribution(
        run_id=uuid4(),
        target_id="fixture-target",
        session_key="session-1",
        operation_key="operation-1",
    )


async def test_projector_creates_widget_from_correlated_tool_and_resource() -> None:
    attribution = _attribution()
    events = InMemoryWidgetEventStore()
    projector = McpAppsLifecycleProjector(
        "session-1",
        AttributionReader(attribution),
        events,
    )
    await _observe_completed_tool_operation(projector)

    await projector.observe(
        ResourceRead(
            session_key="session-1",
            operation_key="operation-1",
            requested_uri="ui://fixture/inspect",
            result=ReadResourceResult(
                contents=(
                    ResourceContent(
                        uri="ui://fixture/inspect",
                        mime_type="text/html;profile=mcp-app",
                        text="<p>fixture</p>",
                    ),
                ),
                metadata={"requestId": "resource-1"},
            ),
        )
    )

    [event] = await events.list_for_run(attribution.run_id)
    assert isinstance(event, WidgetCreated)
    assert event.widget.operation_key == "operation-1"
    assert event.widget.tool_name == "inspect"
    assert event.widget.tool_result.structured_content == {"value": 42}
    assert event.widget.application_resource_uri == "ui://fixture/inspect"
    assert event.widget.resource_contents[0].text == "<p>fixture</p>"
    assert event.widget.resource_metadata == {"requestId": "resource-1"}


async def test_projector_preserves_tool_result_when_widget_resource_fails() -> None:
    attribution = _attribution()
    events = InMemoryWidgetEventStore()
    projector = McpAppsLifecycleProjector(
        "session-1",
        AttributionReader(attribution),
        events,
    )
    await _observe_completed_tool_operation(projector)

    await projector.observe(
        BridgeErrorRaised(
            session_key="session-1",
            operation="application_resource_load",
            operation_key="operation-1",
            failure=BridgeFailure(
                code=BridgeFailureCode.UPSTREAM_PROTOCOL,
                message="resource unavailable",
            ),
        )
    )

    [event] = await events.list_for_run(attribution.run_id)
    assert isinstance(event, WidgetFailed)
    assert event.tool_result.content == ({"type": "text", "text": "completed"},)
    assert event.application_resource_uri == "ui://fixture/inspect"
    assert event.error_message == "resource unavailable"


async def test_projector_ignores_tool_operation_without_run_attribution() -> None:
    events = InMemoryWidgetEventStore()
    projector = McpAppsLifecycleProjector(
        "session-1",
        AttributionReader(None),
        events,
    )
    await _observe_completed_tool_operation(projector)
    await projector.observe(
        ResourceRead(
            session_key="session-1",
            operation_key="operation-1",
            requested_uri="ui://fixture/inspect",
            result=ReadResourceResult(
                contents=(
                    ResourceContent(
                        uri="ui://fixture/inspect",
                        text="<p>fixture</p>",
                    ),
                ),
            ),
        )
    )

    assert await events.list_for_run(uuid4()) == ()


async def test_composed_observers_attribute_before_projecting_widget() -> None:
    target = AgentTarget(
        target_id="fixture-target",
        runtime_profile=AgentRuntimeProfile(
            integration_kind="fixture",
            interface=AgentRuntimeInterface.OPENAI_CHAT_COMPLETIONS,
        ),
        endpoint_assignment=AgentEndpointAssignment(endpoint_slug="fixture-endpoint"),
    )
    coordinator = AgentRunCoordinator((target,))
    attributions = InMemoryOperationRunAttributionRegistry()
    events = InMemoryWidgetEventStore()
    factory = CompositeBridgeSessionObserverFactory(
        (
            AgentOperationAttributionObserverFactory(coordinator, attributions),
            McpAppsLifecycleObserverFactory("fixture-endpoint", attributions, events),
        )
    )
    observer = factory.create("session-1", "fixture-endpoint")
    assert observer is not None
    run_id = uuid4()
    await coordinator.start_run(target.target_id, run_id)

    await observer.observe(
        ToolsPublished(
            session_key="session-1",
            tools=(ToolDescriptor(name="inspect", ui_resource_uri="ui://fixture/inspect"),),
        )
    )
    await observer.observe(
        ToolCallStarted(
            session_key="session-1",
            operation_key="operation-1",
            tool_name="inspect",
        )
    )
    await observer.observe(
        ToolCallCompleted(
            session_key="session-1",
            operation_key="operation-1",
            result=ToolCallResult(content=({"type": "text", "text": "completed"},)),
        )
    )
    await observer.observe(
        ResourceRead(
            session_key="session-1",
            operation_key="operation-1",
            requested_uri="ui://fixture/inspect",
            result=ReadResourceResult(
                contents=(
                    ResourceContent(
                        uri="ui://fixture/inspect",
                        text="<p>fixture</p>",
                    ),
                ),
            ),
        )
    )

    [event] = await events.list_for_run(run_id)
    assert isinstance(event, WidgetCreated)
    assert event.widget.target_id == target.target_id
    assert event.widget.operation_key == "operation-1"
    await coordinator.finish_run(target.target_id, run_id)
