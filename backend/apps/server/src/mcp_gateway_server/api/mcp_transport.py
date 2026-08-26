"""Inbound ASGI transport for published MCP endpoints."""

from __future__ import annotations

import re
from typing import cast
from urllib.parse import parse_qs

import anyio
from fastapi import Response
from mcp_gateway_service import BridgeSessionRuntime, GatewaySessionCoordinator
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def create_mcp_transport_app(manager: GatewaySessionCoordinator) -> ASGIApp:
    async def mcp_transport_app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await _not_found(scope, receive, send)
            return

        path_parts = _relative_path(scope).strip("/").split("/")
        endpoint_slug = path_parts[0]
        transport_path = path_parts[1:]
        if not endpoint_slug or len(transport_path) > 1:
            await _not_found(scope, receive, send)
            return
        if manager.resolve_published_endpoint(endpoint_slug) is None:
            await _not_found(scope, receive, send)
            return

        method = scope.get("method", "GET")
        if method not in {"GET", "POST", "DELETE"}:
            await _not_found(scope, receive, send)
            return

        if transport_path:
            if transport_path == ["sse"] and method == "GET":
                active = await manager.open_session(endpoint_slug)
                await _handle_new_sse_session(
                    manager,
                    active,
                    endpoint_slug,
                    scope,
                    receive,
                    send,
                )
                return
            if transport_path == ["messages"] and method == "POST":
                transport_session_id = _sse_session_id(scope)
                if transport_session_id is None:
                    await _missing_sse_session(scope, receive, send)
                    return
                active = await manager.resolve_session(
                    endpoint_slug,
                    transport_session_id,
                )
                if active is None:
                    await _session_not_found(scope, receive, send)
                    return
                await active.downstream.handle_sse_post(scope, receive, send)
                return
            await _not_found(scope, receive, send)
            return

        transport_session_id = _request_header(scope, b"mcp-session-id")
        if transport_session_id is not None:
            active = await manager.resolve_session(
                endpoint_slug,
                transport_session_id,
            )
            if active is None:
                await _session_not_found(scope, receive, send)
                return
            try:
                await active.downstream.handle_streamable_http(scope, receive, send)
            finally:
                if method == "DELETE":
                    await _close_session(manager, active)
            return

        if method != "POST":
            await _missing_session(scope, receive, send)
            return

        active = await manager.open_session(endpoint_slug)
        await _handle_new_session(manager, active, scope, receive, send)

    return mcp_transport_app


async def _handle_new_session(
    manager: GatewaySessionCoordinator,
    active: BridgeSessionRuntime,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    response_session_id: str | None = None

    async def capture_session_id(message: Message) -> None:
        nonlocal response_session_id
        if message["type"] == "http.response.start":
            candidate_session_id = _message_header(message, b"mcp-session-id")
            status = message["status"]
            if candidate_session_id is not None and 200 <= status < 300:
                response_session_id = candidate_session_id
                await manager.bind_transport_session(active, response_session_id)
            elif candidate_session_id is not None:
                message = _without_message_header(message, b"mcp-session-id")
        await send(message)

    try:
        await active.downstream.handle_streamable_http(scope, receive, capture_session_id)
        if response_session_id is None:
            await manager.close_session(active)
    except BaseException:
        await _close_session(manager, active)
        raise


async def _handle_new_sse_session(
    manager: GatewaySessionCoordinator,
    active: BridgeSessionRuntime,
    endpoint_slug: str,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
    response_buffer = bytearray()
    response_session_id: str | None = None

    async def capture_session_id(message: Message) -> None:
        nonlocal response_session_id
        body = message.get("body")
        if response_session_id is None and isinstance(body, bytes):
            response_buffer.extend(body)
            response_session_id = _find_sse_session_id(response_buffer)
            if response_session_id is not None:
                await manager.bind_transport_session(active, response_session_id)
        await send(message)

    sse_scope = _with_endpoint_root_path(scope, endpoint_slug)
    try:
        await active.downstream.handle_sse(sse_scope, receive, capture_session_id)
    finally:
        await _close_session(manager, active)


async def _close_session(
    manager: GatewaySessionCoordinator,
    active: BridgeSessionRuntime,
) -> None:
    with anyio.CancelScope(shield=True):
        await manager.close_session(active)


def _request_header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("ascii")
    return None


def _sse_session_id(scope: Scope) -> str | None:
    query = parse_qs(scope.get("query_string", b"").decode("ascii", errors="ignore"))
    values = query.get("session_id") or query.get("sessionId")
    return values[0] if values else None


def _find_sse_session_id(response_buffer: bytearray) -> str | None:
    match = re.search(rb"(?:session_id|sessionId)=([0-9a-fA-F-]{32,36})", response_buffer)
    return match.group(1).decode("ascii") if match is not None else None


def _relative_path(scope: Scope) -> str:
    path = scope.get("path", "")
    root_path = scope.get("root_path", "")
    if root_path and path.startswith(root_path):
        return path[len(root_path) :]
    return path


def _with_endpoint_root_path(scope: Scope, endpoint_slug: str) -> Scope:
    adjusted_scope: Scope = dict(scope)
    root_path = scope.get("root_path", "").rstrip("/")
    adjusted_scope["root_path"] = f"{root_path}/{endpoint_slug}"
    return adjusted_scope


def _message_header(message: Message, name: bytes) -> str | None:
    for key, value in message.get("headers", []):
        if key.lower() == name:
            return value.decode("ascii")
    return None


def _without_message_header(message: Message, name: bytes) -> Message:
    return cast(
        Message,
        {
            **message,
            "headers": [
                (key, value) for key, value in message.get("headers", []) if key.lower() != name
            ],
        },
    )


async def _not_found(scope: Scope, receive: Receive, send: Send) -> None:
    response = Response(status_code=404)
    await response(scope, receive, send)


async def _session_not_found(scope: Scope, receive: Receive, send: Send) -> None:
    response = Response("MCP session not found", status_code=404)
    await response(scope, receive, send)


async def _missing_session(scope: Scope, receive: Receive, send: Send) -> None:
    response = Response("Missing mcp-session-id", status_code=400)
    await response(scope, receive, send)


async def _missing_sse_session(scope: Scope, receive: Receive, send: Send) -> None:
    response = Response("Missing SSE session_id", status_code=400)
    await response(scope, receive, send)
