"""Session-scoped routing contracts for downstream MCP method handling."""

from __future__ import annotations

import re
from base64 import urlsafe_b64encode
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Protocol

import anyio
from pydantic import AnyUrl

from mcpapps_bridge.domain import EndpointBindingRevision, EndpointTopologyRevision
from mcpapps_bridge.models import (
    AppResource,
    ResourceDescriptor,
    ToolCallResult,
    ToolDescriptor,
    UpstreamAvailability,
    UpstreamAvailabilityStatus,
    UpstreamInitialization,
)
from mcpapps_bridge.session import BridgeSessionStore

from .runtime import UpstreamRuntime


class McpSessionRouter(Protocol):
    @property
    def identity(self) -> UpstreamInitialization: ...

    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def list_tools(self) -> list[ToolDescriptor]: ...

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult: ...

    async def preload_tool_resource(self, tool_name: str) -> None: ...

    async def list_resources(self) -> list[ResourceDescriptor]: ...

    async def read_resource(self, uri: str) -> AppResource: ...


class PassthroughRouter:
    def __init__(self, runtime: UpstreamRuntime, session_store: BridgeSessionStore) -> None:
        self._runtime = runtime
        self._session_store = session_store

    @property
    def identity(self) -> UpstreamInitialization:
        return self._runtime.identity

    async def start(self) -> None:
        await self._runtime.start()
        await self._session_store.start(self._runtime.identity)
        await self.list_tools()
        await self.list_resources()

    async def close(self) -> None:
        await self._runtime.close()

    async def list_tools(self) -> list[ToolDescriptor]:
        tools = await self._runtime.refresh_tools()
        await self._session_store.register_tools(tools)
        return tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolCallResult:
        return await self._runtime.call_tool(tool_name, arguments)

    async def preload_tool_resource(self, tool_name: str) -> None:
        try:
            await self._runtime.preload_tool_resource(tool_name)
        except Exception as exc:
            await self._session_store.record_error(
                f"Failed to preload UI resource for tool '{tool_name}'",
                details={"reason": str(exc)},
            )

    async def list_resources(self) -> list[ResourceDescriptor]:
        return await self._runtime.refresh_resources()

    async def read_resource(self, uri: str) -> AppResource:
        resource = await self._runtime.read_and_cache_resource(uri)
        await self._session_store.load_resource(resource)
        return resource


@dataclass
class BoundUpstreamRuntime:
    binding: EndpointBindingRevision
    runtime: UpstreamRuntime
    availability: UpstreamAvailability

    @property
    def namespace(self) -> str:
        if self.binding.namespace is None:
            raise ValueError("Aggregate binding has no namespace")
        return self.binding.namespace


class AggregateRouter:
    def __init__(
        self,
        revision: EndpointTopologyRevision,
        session_store: BridgeSessionStore,
        runtime_factory: Callable[[EndpointBindingRevision], UpstreamRuntime],
        *,
        version: str,
    ) -> None:
        self._revision = revision
        self._session_store = session_store
        self._identity = UpstreamInitialization(
            server_name=revision.display_name,
            server_version=version,
            supports_tools=True,
            supports_resources=True,
        )
        self._bindings = [
            BoundUpstreamRuntime(
                binding=binding,
                runtime=runtime_factory(binding),
                availability=UpstreamAvailability(
                    binding_revision_id=str(binding.binding_revision_id),
                    namespace=binding.namespace,
                    upstream_revision_id=str(binding.upstream.revision_id),
                    upstream_server_id=str(binding.upstream.server_id),
                ),
            )
            for binding in revision.bindings
            if binding.enabled
        ]
        self._bindings.sort(
            key=lambda bound: (
                bound.binding.priority,
                bound.namespace,
                str(bound.binding.binding_revision_id),
            )
        )
        self._tool_routes: dict[str, tuple[BoundUpstreamRuntime, str]] = {}
        self._resource_routes: dict[str, tuple[BoundUpstreamRuntime, str]] = {}

    @property
    def identity(self) -> UpstreamInitialization:
        return self._identity

    async def start(self) -> None:
        await self._session_store.start(self._identity)
        await self._publish_availability()

    async def close(self) -> None:
        async with anyio.create_task_group() as task_group:
            for bound in self._bindings:
                task_group.start_soon(bound.runtime.close)

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
        await self._session_store.register_tools(tools)
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

    async def read_resource(self, uri: str) -> AppResource:
        route = self._resource_routes.get(_canonical_uri(uri))
        if route is None:
            raise KeyError(f"Unknown aggregate resource URI: {uri}")
        bound, upstream_uri = route
        try:
            await bound.runtime.start()
            resource = await bound.runtime.read_and_cache_resource(upstream_uri)
            self._mark_available(bound)
        except Exception as exc:
            self._mark_failed(bound, "resource_read", exc)
            await bound.runtime.close()
            await self._publish_availability()
            raise
        await self._publish_availability()
        public_resource = resource.model_copy(update={"uri": _canonical_uri(uri)})
        await self._session_store.load_resource(public_resource)
        return public_resource

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
                "metadata": _rewrite_ui_metadata(tool.metadata, public_ui_uri),
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
        content: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
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
        return rewritten

    def _register_resource_route(self, bound: BoundUpstreamRuntime, upstream_uri: str) -> str:
        public_uri = _public_resource_uri(bound.namespace, upstream_uri)
        canonical_public_uri = _canonical_uri(public_uri)
        existing = self._resource_routes.get(canonical_public_uri)
        route = (bound, upstream_uri)
        if existing is not None and existing != route:
            raise ValueError(f"Aggregate resource URI collision: {canonical_public_uri}")
        self._resource_routes[canonical_public_uri] = route
        return canonical_public_uri

    def _mark_available(self, bound: BoundUpstreamRuntime) -> None:
        if (
            bound.availability.status is UpstreamAvailabilityStatus.AVAILABLE
            and bound.availability.identity == bound.runtime.identity
            and bound.availability.failure_kind is None
            and bound.availability.error_message is None
        ):
            return
        bound.availability = bound.availability.model_copy(
            update={
                "status": UpstreamAvailabilityStatus.AVAILABLE,
                "identity": bound.runtime.identity,
                "failure_kind": None,
                "error_message": None,
                "updated_at": datetime.now(timezone.utc),
            }
        )

    def _mark_failed(
        self,
        bound: BoundUpstreamRuntime,
        failure_kind: str,
        error: Exception,
    ) -> None:
        if (
            bound.availability.status is UpstreamAvailabilityStatus.FAILED
            and bound.availability.failure_kind == failure_kind
            and bound.availability.error_message == str(error)
        ):
            return
        bound.availability = bound.availability.model_copy(
            update={
                "status": UpstreamAvailabilityStatus.FAILED,
                "failure_kind": failure_kind,
                "error_message": str(error),
                "updated_at": datetime.now(timezone.utc),
            }
        )

    async def _publish_availability(self) -> None:
        await self._session_store.set_upstream_availability(
            [bound.availability for bound in self._bindings]
        )


def _public_resource_uri(namespace: str, upstream_uri: str) -> str:
    if upstream_uri.startswith("ui://"):
        digest = sha256(upstream_uri.encode("utf-8")).digest()[:18]
        token = urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return f"ui://{namespace}/{token}"
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", upstream_uri) is None:
        raise ValueError(f"Upstream resource URI has no valid scheme: {upstream_uri}")
    return f"{namespace}+{upstream_uri}"


def _canonical_uri(uri: str) -> str:
    return str(AnyUrl(uri))


def _rewrite_ui_metadata(
    metadata: dict[str, Any],
    public_ui_uri: str | None,
) -> dict[str, Any]:
    rewritten = dict(metadata)
    if public_ui_uri is None:
        return rewritten
    if "ui" in rewritten:
        rewritten["ui"] = (
            {**rewritten["ui"], "resourceUri": public_ui_uri}
            if isinstance(rewritten["ui"], dict)
            else public_ui_uri
        )
    if "ui/resourceUri" in rewritten:
        rewritten["ui/resourceUri"] = public_ui_uri
    if "openai/outputTemplate" in rewritten:
        rewritten["openai/outputTemplate"] = public_ui_uri
    if "openai/resourceUri" in rewritten:
        rewritten["openai/resourceUri"] = public_ui_uri
    if isinstance(rewritten.get("openai"), dict):
        openai = dict(rewritten["openai"])
        if "resourceUri" in openai:
            openai["resourceUri"] = public_ui_uri
        if "outputTemplate" in openai:
            openai["outputTemplate"] = public_ui_uri
        rewritten["openai"] = openai
    nested_meta = rewritten.get("_meta")
    if isinstance(nested_meta, dict):
        rewritten_nested_meta = dict(nested_meta)
        if "ui" in rewritten_nested_meta:
            rewritten_nested_meta["ui"] = (
                {**rewritten_nested_meta["ui"], "resourceUri": public_ui_uri}
                if isinstance(rewritten_nested_meta["ui"], dict)
                else public_ui_uri
            )
        if "ui/resourceUri" in rewritten_nested_meta:
            rewritten_nested_meta["ui/resourceUri"] = public_ui_uri
        rewritten["_meta"] = rewritten_nested_meta
    return rewritten


def _all_bindings_failed_message(operation: str, failures: dict[str, Exception]) -> str:
    details = ", ".join(f"{namespace}: {error}" for namespace, error in sorted(failures.items()))
    return f"All aggregate bindings failed during {operation}: {details}"
