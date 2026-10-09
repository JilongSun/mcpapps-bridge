"""Typed process capability assembly; deployment resources remain server-owned."""

from dataclasses import dataclass

from ..agent_host import (
    AgentHostService,
    AgentSessionService,
    AgentSessionRepository,
    AgentRuntime,
    AgentTarget,
    AgentRunCoordinator,
    AgentOperationAttributionObserverFactory,
    InMemoryOperationRunAttributionRegistry,
    OperationRunAttributionRegistry,
    RuntimeSessionCatalog,
    RuntimeSessionHistory,
    RuntimeSessionExecution,
    RuntimeSessionRunControl,
    restore_target_run_ownership,
)
from ..mcp_apps import InMemoryWidgetEventStore, McpAppsLifecycleObserverFactory
from ..gateway.sessions import BridgeSessionObserverFactory
from .service import HostEventStream
from .settlement import HostRunSettlement, HostObservationFactory


@dataclass(frozen=True)
class NativeSessionPorts:
    binding_id: str
    catalog: RuntimeSessionCatalog
    history: RuntimeSessionHistory
    execution: RuntimeSessionExecution
    control: RuntimeSessionRunControl


@dataclass(frozen=True)
class McpAppsComposition:
    events: InMemoryWidgetEventStore
    bridge_observer_factory: McpAppsLifecycleObserverFactory


def compose_mcp_apps(
    endpoint_slug: str, operation_attributions: OperationRunAttributionRegistry
) -> McpAppsComposition:
    events = InMemoryWidgetEventStore()
    return McpAppsComposition(
        events=events,
        bridge_observer_factory=McpAppsLifecycleObserverFactory(
            endpoint_slug, operation_attributions, events
        ),
    )


@dataclass(frozen=True)
class HostCapabilityComposition:
    agent_host: AgentHostService
    sessions: AgentSessionService | None
    attributions: InMemoryOperationRunAttributionRegistry
    bridge_observer_factory: HostObservationFactory
    mcp_apps: McpAppsComposition | None
    events: HostEventStream
    settlement: HostRunSettlement


async def compose_host_capabilities(
    target: AgentTarget,
    runtime: AgentRuntime,
    repository: AgentSessionRepository,
    *,
    native: NativeSessionPorts | None = None,
    mcp_apps_enabled: bool = False,
    observer_timeout_seconds: float = 5.0,
    settlement_timeout_seconds: float = 5.0,
) -> HostCapabilityComposition:
    coordinator = AgentRunCoordinator((target,))
    await restore_target_run_ownership(repository, coordinator, target.target_id)
    attributions = InMemoryOperationRunAttributionRegistry()
    factories: list[BridgeSessionObserverFactory] = [
        AgentOperationAttributionObserverFactory(coordinator, attributions)
    ]
    apps = (
        compose_mcp_apps(target.endpoint_assignment.endpoint_slug, attributions)
        if mcp_apps_enabled
        else None
    )
    if apps is not None:
        factories.append(apps.bridge_observer_factory)
    settlement = HostRunSettlement(
        apps.events if apps is not None else None, timeout_seconds=settlement_timeout_seconds
    )
    service = AgentHostService(target, runtime, coordinator, settlement)
    sessions = (
        AgentSessionService(
            target_id=target.target_id,
            runtime_binding_id=native.binding_id,
            repository=repository,
            catalog=native.catalog,
            history=native.history,
            execution=native.execution,
            control=native.control,
            coordinator=coordinator,
            settlement=settlement,
        )
        if native is not None
        else None
    )
    return HostCapabilityComposition(
        agent_host=service,
        sessions=sessions,
        attributions=attributions,
        bridge_observer_factory=HostObservationFactory(
            coordinator,
            attributions,
            settlement,
            factories,
            timeout_seconds=observer_timeout_seconds,
        ),
        mcp_apps=apps,
        events=HostEventStream(service, apps.events if apps is not None else None, settlement),
        settlement=settlement,
    )
