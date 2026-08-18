"""Pure conversion from transitional bridge models to bridge-core contracts."""

from __future__ import annotations

from mcp_bridge_core import (
    AppResource as CoreAppResource,
    ToolCallResult as CoreToolCallResult,
    ToolDescriptor as CoreToolDescriptor,
    UpstreamIdentity,
)

from mcpapps_bridge.models import (
    AppResource,
    ToolCallResult,
    ToolDescriptor,
    UpstreamInitialization,
)


def to_core_identity(identity: UpstreamInitialization) -> UpstreamIdentity:
    return UpstreamIdentity.model_validate(identity.model_dump())


def to_core_tool(tool: ToolDescriptor) -> CoreToolDescriptor:
    return CoreToolDescriptor.model_validate(tool.model_dump())


def to_core_tool_result(result: ToolCallResult) -> CoreToolCallResult:
    return CoreToolCallResult.model_validate(result.model_dump())


def to_core_resource(resource: AppResource) -> CoreAppResource:
    return CoreAppResource.model_validate(resource.model_dump())
