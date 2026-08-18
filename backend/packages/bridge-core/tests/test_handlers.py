from __future__ import annotations

from typing import Any

import pytest

from mcp_bridge_core import (
    AppResource,
    BridgeFailureCode,
    BridgeObservation,
    ResourceDescriptor,
    ToolCallCompleted,
    ToolCallResult,
    ToolCallStarted,
    ToolDescriptor,
)
from mcp_bridge_core.handlers import ProxyHandlers


class RecordingObserver:
    def __init__(self) -> None:
        self.events: list[BridgeObservation] = []

    async def observe(self, event: BridgeObservation) -> None:
        self.events.append(event)


class ToolRouter:
    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.preloaded: list[str] = []

    async def list_tools(self) -> list[ToolDescriptor]:
        return []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        if self._error is not None:
            raise self._error
        return ToolCallResult(content=({"type": "text", "text": tool_name},))

    async def preload_tool_resource(self, tool_name: str) -> None:
        self.preloaded.append(tool_name)

    async def list_resources(self) -> list[ResourceDescriptor]:
        return []

    async def read_resource(self, uri: str) -> AppResource:
        return AppResource(uri=uri, mime_type="text/plain", text="fixture")


async def test_proxy_handlers_correlate_tool_call_observations() -> None:
    observer = RecordingObserver()
    router = ToolRouter()
    handlers = ProxyHandlers(router, observer, "session-1")

    result = await handlers.call_tool("fixture__inspect", {"depth": 2})

    assert result.isError is False
    started = next(event for event in observer.events if isinstance(event, ToolCallStarted))
    completed = next(event for event in observer.events if isinstance(event, ToolCallCompleted))
    assert started.operation_key == completed.operation_key
    assert started.tool_name == "fixture__inspect"
    assert completed.result is not None
    assert completed.failure is None
    assert router.preloaded == ["fixture__inspect"]


async def test_proxy_handlers_emit_typed_failure_before_reraising() -> None:
    observer = RecordingObserver()
    handlers = ProxyHandlers(
        ToolRouter(error=RuntimeError("upstream failed")), observer, "session-1"
    )

    with pytest.raises(RuntimeError, match="upstream failed"):
        await handlers.call_tool("fixture__inspect", {})

    started = next(event for event in observer.events if isinstance(event, ToolCallStarted))
    completed = next(event for event in observer.events if isinstance(event, ToolCallCompleted))
    assert completed.operation_key == started.operation_key
    assert completed.result is None
    assert completed.failure is not None
    assert completed.failure.code is BridgeFailureCode.UPSTREAM_PROTOCOL
