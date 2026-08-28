"""Framework-neutral ASGI dispatcher for downstream MCP transports.

The dispatcher owns MCP transport mechanics: mounted-path parsing, streamable HTTP session headers,
legacy SSE query correlation, response capture, and transport closure. It treats endpoint keys and
session objects as opaque values supplied by an application-owned broker. It never imports managed
topology, persistence, FastAPI, or deployment configuration.
"""

from __future__ import annotations

import re
from typing import Protocol, TypeVar
from urllib.parse import parse_qs

import anyio
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class McpTransportSession(Protocol):
    async def handle_streamable_http(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None: ...

    async def handle_sse(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None: ...

    async def handle_sse_post(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None: ...


SessionT = TypeVar("SessionT")


class McpSessionBroker(Protocol[SessionT]):
    async def open_session(self, endpoint_key: str) -> SessionT | None: ...

    async def resolve_session(
        self,
        endpoint_key: str,
        transport_session_id: str,
    ) -> SessionT | None: ...

    async def bind_transport_session(
        self,
        session: SessionT,
        transport_session_id: str,
    ) -> None: ...

    async def close_session(self, session: SessionT) -> None: ...

    def transport(self, session: SessionT) -> McpTransportSession: ...


def create_mcp_asgi_app(broker: McpSessionBroker[SessionT]) -> ASGIApp:
    """Create the raw MCP ASGI surface mounted by a deployment host."""

    async def mcp_asgi_app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await _not_found(scope, receive, send)
            return

        path_parts = _relative_path(scope).strip("/").split("/")
        endpoint_key = path_parts[0]
        transport_path = path_parts[1:]
        if not endpoint_key or len(transport_path) > 1:
            await _not_found(scope, receive, send)
            return

        method = scope.get("method", "GET")
        if method not in {"GET", "POST", "DELETE"}:
            await _not_found(scope, receive, send)
            return

        if transport_path:
            if transport_path == ["sse"] and method == "GET":
                session = await broker.open_session(endpoint_key)
                if session is None:
                    await _not_found(scope, receive, send)
                    return
                await _handle_new_sse_session(
                    broker,
                    session,
                    endpoint_key,
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
                session = await broker.resolve_session(endpoint_key, transport_session_id)
                if session is None:
                    await _session_not_found(scope, receive, send)
                    return
                await broker.transport(session).handle_sse_post(scope, receive, send)
                return
            await _not_found(scope, receive, send)
            return

        transport_session_id = _request_header(scope, b"mcp-session-id")
        if transport_session_id is not None:
            session = await broker.resolve_session(endpoint_key, transport_session_id)
            if session is None:
                await _session_not_found(scope, receive, send)
                return
            try:
                await broker.transport(session).handle_streamable_http(scope, receive, send)
            finally:
                if method == "DELETE":
                    await _close_session(broker, session)
            return

        if method != "POST":
            await _missing_session(scope, receive, send)
            return

        session = await broker.open_session(endpoint_key)
        if session is None:
            await _not_found(scope, receive, send)
            return
        await _handle_new_streamable_session(broker, session, scope, receive, send)

    return mcp_asgi_app


async def _handle_new_streamable_session(
    broker: McpSessionBroker[SessionT],
    session: SessionT,
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
                await broker.bind_transport_session(session, response_session_id)
            elif candidate_session_id is not None:
                message = _without_message_header(message, b"mcp-session-id")
        await send(message)

    try:
        await broker.transport(session).handle_streamable_http(
            scope,
            receive,
            capture_session_id,
        )
        if response_session_id is None:
            await broker.close_session(session)
    except BaseException:
        await _close_session(broker, session)
        raise


async def _handle_new_sse_session(
    broker: McpSessionBroker[SessionT],
    session: SessionT,
    endpoint_key: str,
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
                await broker.bind_transport_session(session, response_session_id)
        await send(message)

    sse_scope = _with_endpoint_root_path(scope, endpoint_key)
    try:
        await broker.transport(session).handle_sse(sse_scope, receive, capture_session_id)
    finally:
        await _close_session(broker, session)


async def _close_session(
    broker: McpSessionBroker[SessionT],
    session: SessionT,
) -> None:
    with anyio.CancelScope(shield=True):
        await broker.close_session(session)


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


def _with_endpoint_root_path(scope: Scope, endpoint_key: str) -> Scope:
    adjusted_scope: Scope = dict(scope)
    root_path = scope.get("root_path", "").rstrip("/")
    adjusted_scope["root_path"] = f"{root_path}/{endpoint_key}"
    return adjusted_scope


def _message_header(message: Message, name: bytes) -> str | None:
    for key, value in message.get("headers", []):
        if key.lower() == name:
            return value.decode("ascii")
    return None


def _without_message_header(message: Message, name: bytes) -> Message:
    return {
        **message,
        "headers": [
            (key, value) for key, value in message.get("headers", []) if key.lower() != name
        ],
    }


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
