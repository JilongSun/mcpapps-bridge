"""Namespaced multi-upstream routing for one bridge session."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import anyio
from anyio.abc import TaskGroup

from ..contracts import (
    BindingAvailabilityChanged,
    BindingAvailabilityStatus,
    BridgeFailure,
    BridgeFailureCode,
    BridgeSessionStarted,
    ReadResourceResult,
    ResourceDescriptor,
    ResourceRead,
    ToolCallResult,
    ToolDescriptor,
    ToolsPublished,
    BindingPlan,
    BridgeObserver,
    EndpointPlan,
    UpstreamIdentity,
)
from ..upstream.runtime import UpstreamRuntime
from .resource_uris import canonical_uri, public_resource_uri, rewrite_ui_metadata


@dataclass
class BindingAvailability:
    binding_key: str
    status: BindingAvailabilityStatus = BindingAvailabilityStatus.UNKNOWN
    identity: UpstreamIdentity | None = None
    failure_kind: str | None = None
    error_message: str | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class BoundUpstreamRuntime:
    binding: BindingPlan
    runtime: UpstreamRuntime
    availability: BindingAvailability

    @property
    def namespace(self) -> str:
        if self.binding.namespace is None:
            raise ValueError("Aggregate binding has no namespace")
        return self.binding.namespace


class AggregateRouter:
    def __init__(
        self,
        plan: EndpointPlan,
        observer: BridgeObserver,
        session_key: str,
        runtime_factory: Callable[[BindingPlan], UpstreamRuntime],
        worker_task_group: TaskGroup,
        *,
        version: str,
    ) -> None:
        self._observer = observer
        self._session_key = session_key
        self._worker_task_group = worker_task_group
        self._identity = UpstreamIdentity(
            server_name=plan.display_name,
            server_version=version,
            supports_tools=plan.capabilities.tools,
            supports_resources=plan.capabilities.resources,
        )
        self._bindings = [
            BoundUpstreamRuntime(
                binding=binding,
                runtime=runtime_factory(binding),
                availability=BindingAvailability(binding_key=binding.binding_key),
            )
            for binding in plan.bindings
        ]
        self._bindings.sort(
            key=lambda bound: (
                bound.binding.priority,
                bound.namespace,
                bound.binding.binding_key,
            )
        )
        self._tool_routes: dict[str, tuple[BoundUpstreamRuntime, str]] = {}
        self._resource_routes: dict[str, tuple[BoundUpstreamRuntime, str]] = {}
        self._published_availability: dict[str, BindingAvailability] = {}

    @property
    def identity(self) -> UpstreamIdentity:
        return self._identity

    async def start(self) -> None:
        for bound in self._bindings:
            await bound.runtime.start_worker(self._worker_task_group)
        try:
            await self._observer.observe(
                BridgeSessionStarted(
                    session_key=self._session_key,
                    identity=self._identity,
                )
            )
            await self._publish_availability()
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        errors: list[Exception] = []
        for bound in self._bindings:
            try:
                await bound.runtime.shutdown_worker()
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup("Failed to close aggregate upstream workers", errors)

    async def list_tools(self) -> list[ToolDescriptor]:
        discovered: dict[str, list[ToolDescriptor]] = {}
        failures: dict[str, Exception] = {}

        async def discover(bound: BoundUpstreamRuntime) -> None:
            try:
                await bound.runtime.start()
                tools = await bound.runtime.refresh_tools()
                discovered[bound.namespace] = [self._public_tool(bound, tool) for tool in tools]
                self._mark_available(bound)
            except Exception as exc:
                failures[bound.namespace] = exc
                self._mark_failed(bound, "discovery", exc)
                await bound.runtime.close()

        async with anyio.create_task_group() as task_group:
            for bound in self._bindings:
                task_group.start_soon(discover, bound)
        await self._publish_availability()
        if not discovered:
            raise RuntimeError(_all_bindings_failed_message("tool discovery", failures))

        tools = [tool for bound in self._bindings for tool in discovered.get(bound.namespace, [])]
        await self._observer.observe(
            ToolsPublished(session_key=self._session_key, tools=tuple(tools))
        )
        return tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolCallResult:
        route = self._tool_routes.get(tool_name)
        if route is None:
            await self.list_tools()
            route = self._tool_routes.get(tool_name)
        if route is None:
            raise KeyError(f"Unknown aggregate tool: {tool_name}")
        bound, upstream_tool_name = route
        try:
            await bound.runtime.start()
            result = await bound.runtime.call_tool(upstream_tool_name, arguments)
            self._mark_available(bound)
        except Exception as exc:
            self._mark_failed(bound, "tool_call", exc)
            await bound.runtime.close()
            await self._publish_availability()
            raise
        await self._publish_availability()
        return result.model_copy(update={"content": self._public_content(bound, result.content)})

    async def preload_tool_resource(self, tool_name: str) -> None:
        route = self._tool_routes.get(tool_name)
        if route is None:
            return
        bound, upstream_tool_name = route
        tool = bound.runtime.tool(upstream_tool_name)
        if tool is None or tool.ui_resource_uri is None:
            return
        public_uri = self._register_resource_route(bound, tool.ui_resource_uri)
        try:
            await self.read_resource(public_uri)
        except Exception:
            return

    async def list_resources(self) -> list[ResourceDescriptor]:
        discovered: dict[str, list[ResourceDescriptor]] = {}
        failures: dict[str, Exception] = {}

        async def discover(bound: BoundUpstreamRuntime) -> None:
            try:
                await bound.runtime.start()
                resources = await bound.runtime.refresh_resources()
                discovered[bound.namespace] = [
                    self._public_resource(bound, resource) for resource in resources
                ]
                self._mark_available(bound)
            except Exception as exc:
                failures[bound.namespace] = exc
                self._mark_failed(bound, "discovery", exc)
                await bound.runtime.close()

        async with anyio.create_task_group() as task_group:
            for bound in self._bindings:
                task_group.start_soon(discover, bound)
        await self._publish_availability()
        if not discovered:
            raise RuntimeError(_all_bindings_failed_message("resource discovery", failures))
        return [
            resource for bound in self._bindings for resource in discovered.get(bound.namespace, [])
        ]

    async def read_resource(self, uri: str) -> ReadResourceResult:
        route = self._resource_routes.get(canonical_uri(uri))
        if route is None:
            raise KeyError(f"Unknown aggregate resource URI: {uri}")
        bound, upstream_uri = route
        try:
            await bound.runtime.start()
            result = await bound.runtime.read_and_cache_resource(upstream_uri)
            self._mark_available(bound)
        except Exception as exc:
            self._mark_failed(bound, "resource_read", exc)
            await bound.runtime.close()
            await self._publish_availability()
            raise
        await self._publish_availability()
        public_result = result.model_copy(
            update={
                "contents": tuple(
                    content.model_copy(
                        update={"uri": self._register_resource_route(bound, content.uri)}
                    )
                    for content in result.contents
                )
            },
            deep=True,
        )
        await self._observer.observe(
            ResourceRead(
                session_key=self._session_key,
                binding_key=bound.binding.binding_key,
                requested_uri=canonical_uri(uri),
                result=public_result,
            )
        )
        return public_result

    def _public_tool(
        self,
        bound: BoundUpstreamRuntime,
        tool: ToolDescriptor,
    ) -> ToolDescriptor:
        public_name = f"{bound.namespace}__{tool.name}"
        self._tool_routes[public_name] = (bound, tool.name)
        public_ui_uri = (
            self._register_resource_route(bound, tool.ui_resource_uri)
            if tool.ui_resource_uri is not None
            else None
        )
        return tool.model_copy(
            update={
                "name": public_name,
                "ui_resource_uri": public_ui_uri,
                "metadata": rewrite_ui_metadata(tool.metadata, public_ui_uri),
            },
            deep=True,
        )

    def _public_resource(
        self,
        bound: BoundUpstreamRuntime,
        resource: ResourceDescriptor,
    ) -> ResourceDescriptor:
        return resource.model_copy(
            update={
                "name": f"{bound.namespace}__{resource.name}",
                "uri": self._register_resource_route(bound, resource.uri),
            },
            deep=True,
        )

    def _public_content(
        self,
        bound: BoundUpstreamRuntime,
        content: Sequence[dict[str, Any]],
    ) -> tuple[dict[str, Any], ...]:
        rewritten: list[dict[str, Any]] = []
        for item in content:
            public_item = dict(item)
            if item.get("type") == "resource_link" and isinstance(item.get("uri"), str):
                public_item["uri"] = self._register_resource_route(bound, item["uri"])
            elif item.get("type") == "resource" and isinstance(item.get("resource"), dict):
                resource = dict(item["resource"])
                if isinstance(resource.get("uri"), str):
                    resource["uri"] = self._register_resource_route(bound, resource["uri"])
                public_item["resource"] = resource
            rewritten.append(public_item)
        return tuple(rewritten)

    def _register_resource_route(self, bound: BoundUpstreamRuntime, upstream_uri: str) -> str:
        public_uri = public_resource_uri(bound.namespace, upstream_uri)
        canonical_public_uri = canonical_uri(public_uri)
        existing = self._resource_routes.get(canonical_public_uri)
        route = (bound, upstream_uri)
        if existing is not None and existing != route:
            raise ValueError(f"Aggregate resource URI collision: {canonical_public_uri}")
        self._resource_routes[canonical_public_uri] = route
        return canonical_public_uri

    def _mark_available(self, bound: BoundUpstreamRuntime) -> None:
        if (
            bound.availability.status is BindingAvailabilityStatus.AVAILABLE
            and bound.availability.identity == bound.runtime.identity
            and bound.availability.failure_kind is None
            and bound.availability.error_message is None
        ):
            return
        bound.availability = BindingAvailability(
            binding_key=bound.availability.binding_key,
            status=BindingAvailabilityStatus.AVAILABLE,
            identity=bound.runtime.identity,
            updated_at=datetime.now(timezone.utc),
        )

    def _mark_failed(
        self,
        bound: BoundUpstreamRuntime,
        failure_kind: str,
        error: Exception,
    ) -> None:
        if (
            bound.availability.status is BindingAvailabilityStatus.FAILED
            and bound.availability.failure_kind == failure_kind
            and bound.availability.error_message == str(error)
        ):
            return
        bound.availability = BindingAvailability(
            binding_key=bound.availability.binding_key,
            status=BindingAvailabilityStatus.FAILED,
            identity=bound.availability.identity,
            failure_kind=failure_kind,
            error_message=str(error),
            updated_at=datetime.now(timezone.utc),
        )

    async def _publish_availability(self) -> None:
        for bound in self._bindings:
            availability = bound.availability
            binding_key = availability.binding_key
            if self._published_availability.get(binding_key) == availability:
                continue
            failure = (
                BridgeFailure(
                    code=BridgeFailureCode.BINDING_UNAVAILABLE,
                    message=availability.error_message or "Upstream binding is unavailable",
                    retryable=True,
                    binding_key=binding_key,
                    details={"operation": availability.failure_kind},
                )
                if availability.status is BindingAvailabilityStatus.FAILED
                else None
            )
            await self._observer.observe(
                BindingAvailabilityChanged(
                    session_key=self._session_key,
                    observed_at=availability.updated_at,
                    binding_key=binding_key,
                    status=availability.status,
                    identity=availability.identity,
                    failure=failure,
                )
            )
            self._published_availability[binding_key] = deepcopy(availability)


def _all_bindings_failed_message(operation: str, failures: dict[str, Exception]) -> str:
    details = ", ".join(f"{namespace}: {error}" for namespace, error in sorted(failures.items()))
    return f"All aggregate bindings failed during {operation}: {details}"
