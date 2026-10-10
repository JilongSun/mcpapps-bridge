"""Native Hermes session resources and history, isolated from OpenAI compatibility."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, cast
from urllib.parse import quote
from collections.abc import AsyncGenerator

import anyio
import httpx
from httpx_sse import aconnect_sse
from pydantic import JsonValue, TypeAdapter, ValidationError

from ...application.session_errors import AgentSessionError
from ...contracts.session import (
    AgentHistoryMessage,
    CreateAgentSessionCommand,
    HistoryContent,
    HistoryPageQuery,
    HistoryText,
    HistoryToolCall,
    HistoryUnsupportedContent,
    RuntimeAgentSession,
    RuntimeHistoryPage,
    RuntimeRunHandle,
    RuntimeRunState,
    RuntimeSessionReference,
    RuntimeSessionRunEvent,
    RuntimeSessionRunStarted,
    RuntimeSessionRunCompleted,
    RuntimeSessionTextDelta,
    RuntimeStopReceipt,
    StartSessionRunCommand,
)
from .session_documents import (
    HermesHistoryDocument,
    HermesHistoryMessage,
    HermesSessionCreateRequest,
    HermesSessionDocument,
    HermesSessionChatRequest,
    HermesRunStatusDocument,
    HermesStopDocument,
    HermesSessionStreamPayload,
)
from ...contracts import TokenUsage
from ...contracts.capabilities import RuntimeCapabilityObservation
from .capability_document import (
    HermesCapabilityDocument,
    capability_observation,
    capability_http_failure,
)

JSON_ARGUMENTS = TypeAdapter(dict[str, JsonValue])


class HermesSessionAdapter:
    def __init__(
        self,
        *,
        api_root: str,
        api_key: str,
        runtime_binding_id: str,
        timeout_seconds: float = 120.0,
        settlement_timeout_seconds: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.runtime_binding_id = runtime_binding_id
        if settlement_timeout_seconds <= 0:
            raise ValueError("Settlement timeout must be positive")
        self._settlement_timeout = settlement_timeout_seconds
        self._root = httpx.URL(api_root.rstrip("/") + "/")
        if self._root.scheme not in {"http", "https"} or not self._root.host:
            raise ValueError("Native runtime API root must be an absolute HTTP URL")
        if self._root.query or self._root.fragment or self._root.userinfo:
            raise ValueError(
                "Native runtime API root cannot contain credentials, query, or fragment"
            )
        if not runtime_binding_id:
            raise ValueError("Native runtime requires a stable deployment binding ID")
        self._headers = {"authorization": f"Bearer {api_key}"}
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def inspect_capabilities(self) -> RuntimeCapabilityObservation:
        try:
            response = await self._client.get(
                self._root.join("v1/capabilities"), headers=self._headers
            )
        except httpx.HTTPError:
            return RuntimeCapabilityObservation(
                availability="unavailable", reason="runtime_unavailable"
            )
        if not response.is_success:
            return capability_http_failure(response.status_code)
        try:
            document = HermesCapabilityDocument.model_validate_json(response.content, strict=True)
        except ValueError:
            return RuntimeCapabilityObservation(availability="unknown", reason="invalid_response")
        return capability_observation(document)

    async def create_session(self, command: CreateAgentSessionCommand) -> RuntimeAgentSession:
        response = await self._request(
            "POST",
            "api/sessions",
            json=HermesSessionCreateRequest(title=command.title).model_dump(exclude_none=True),
        )
        try:
            document = HermesSessionDocument.model_validate_json(response.content)
        except ValueError as exc:
            raise _contract_error() from exc
        return RuntimeAgentSession(
            remote_session_id=document.session.id, title=document.session.title
        )

    async def get_session(self, reference: RuntimeSessionReference) -> RuntimeAgentSession:
        self._require_binding(reference)
        response = await self._request("GET", _session_path(reference.remote_session_id))
        try:
            document = HermesSessionDocument.model_validate_json(response.content)
        except ValueError as exc:
            raise _contract_error() from exc
        if document.session.id != reference.remote_session_id:
            raise _contract_error()
        return RuntimeAgentSession(
            remote_session_id=document.session.id, title=document.session.title
        )

    async def read_history(
        self, reference: RuntimeSessionReference, query: HistoryPageQuery
    ) -> RuntimeHistoryPage:
        self._require_binding(reference)
        response = await self._request(
            "GET",
            _session_path(reference.remote_session_id) + "/messages",
            params={"limit": query.limit, "offset": query.offset, "order": query.order},
        )
        try:
            document = HermesHistoryDocument.model_validate_json(response.content)
            pagination = document.pagination
            if (
                (pagination.limit, pagination.offset, pagination.order)
                != (query.limit, query.offset, query.order)
                or pagination.returned != len(document.data)
                or len(document.data) > query.limit
            ):
                raise _contract_error()
            messages = tuple(_history_message(message) for message in document.data)
        except (ValueError, OverflowError, OSError) as exc:
            raise _contract_error() from exc
        return RuntimeHistoryPage(
            remote_session_id=document.session_id,
            messages=messages,
            query=query,
        )

    def _require_binding(self, reference: RuntimeSessionReference) -> None:
        if reference.runtime_binding_id != self.runtime_binding_id:
            raise AgentSessionError(
                "runtime_binding_changed", "Agent Session belongs to another runtime"
            )

    async def request_stop(self, handle: RuntimeRunHandle) -> RuntimeStopReceipt:
        self._require_handle(handle)
        response = await self._request(
            "POST", "v1/runs/" + quote(handle.remote_run_id, safe="") + "/stop", allow_missing=True
        )
        if response.status_code == 404:
            return RuntimeStopReceipt(handle=handle, accepted=False)
        try:
            document = HermesStopDocument.model_validate_json(response.content)
        except ValueError as exc:
            raise _contract_error() from exc
        if document.run_id != handle.remote_run_id:
            raise _contract_error()
        return RuntimeStopReceipt(handle=handle, accepted=True)

    async def get_run_state(self, handle: RuntimeRunHandle) -> RuntimeRunState:
        self._require_handle(handle)
        response = await self._request(
            "GET", "v1/runs/" + quote(handle.remote_run_id, safe=""), allow_missing=True
        )
        if response.status_code == 404:
            return RuntimeRunState(handle=handle, state="unknown")
        try:
            document = HermesRunStatusDocument.model_validate_json(response.content)
        except ValueError as exc:
            raise _contract_error() from exc
        if document.run_id != handle.remote_run_id:
            raise _contract_error()
        return RuntimeRunState(handle=handle, state=document.status)

    def _require_handle(self, handle: RuntimeRunHandle) -> None:
        if handle.runtime_binding_id != self.runtime_binding_id:
            raise AgentSessionError("runtime_binding_changed", "Run belongs to another runtime")
        if handle.remote_run_id in {".", ".."}:
            raise _contract_error()

    async def run_session(
        self, reference: RuntimeSessionReference, command: StartSessionRunCommand
    ) -> AsyncGenerator[RuntimeSessionRunEvent, None]:
        self._require_binding(reference)
        stream_url = str(
            self._root.join(_session_path(reference.remote_session_id) + "/chat/stream")
        )
        handle: RuntimeRunHandle | None = None
        rejected_submission = False
        remote_terminal = False
        final_text: str | None = None
        completion: RuntimeSessionRunCompleted | None = None
        try:
            async with aconnect_sse(
                self._client,
                "POST",
                stream_url,
                headers=self._headers,
                json=HermesSessionChatRequest(message=command.input_text).model_dump(),
            ) as source:
                rejected_submission = not source.response.is_success
                _check_response(source.response)
                async for event in source.aiter_sse():
                    try:
                        payload = HermesSessionStreamPayload.model_validate_json(event.data)
                    except ValueError as exc:
                        raise _contract_error() from exc
                    if handle is not None and payload.run_id != handle.remote_run_id:
                        raise _contract_error()
                    if event.event == "run.started":
                        if handle is not None or payload.session_id != reference.remote_session_id:
                            raise _contract_error()
                        handle = RuntimeRunHandle(
                            runtime_binding_id=self.runtime_binding_id, remote_run_id=payload.run_id
                        )
                        yield RuntimeSessionRunStarted(handle=handle)
                    elif event.event == "assistant.delta":
                        if handle is None or completion is not None:
                            raise _contract_error()
                        if payload.delta:
                            yield RuntimeSessionTextDelta(delta=payload.delta)
                    elif event.event == "assistant.completed":
                        final_text = payload.content
                    elif event.event == "run.completed":
                        if handle is None or final_text is None or completion is not None:
                            raise _contract_error()
                        completion = RuntimeSessionRunCompleted(
                            remote_session_id=payload.session_id,
                            output_text=final_text,
                            usage=TokenUsage(
                                input_tokens=payload.usage.input_tokens,
                                output_tokens=payload.usage.output_tokens,
                            ),
                        )
                        remote_terminal = True
                    elif event.event == "error":
                        if handle is not None:
                            remote_terminal = (await self.get_run_state(handle)).is_terminal
                        raise AgentSessionError(
                            "runtime_unavailable", "Agent Runtime execution failed"
                        )
                    elif event.event == "done":
                        break
                if completion is None:
                    raise _contract_error()
            yield completion
        except httpx.RequestError as exc:
            if handle is None:
                raise AgentSessionError(
                    "run_state_unknown", "Runtime submission outcome is unknown"
                ) from exc
            raise AgentSessionError("runtime_unavailable", "Agent Runtime stream failed") from exc
        finally:
            if handle is not None and not remote_terminal:
                await self._settle(handle)
            elif handle is None and not rejected_submission:
                raise AgentSessionError(
                    "run_state_unknown", "Accepted execution has no recoverable remote Run handle"
                )

    async def _settle(self, handle: RuntimeRunHandle) -> None:
        with anyio.CancelScope(shield=True):
            with anyio.move_on_after(self._settlement_timeout):
                try:
                    await self.request_stop(handle)
                    while True:
                        state = await self.get_run_state(handle)
                        if state.is_terminal:
                            return
                        await anyio.sleep(0.05)
                except AgentSessionError:
                    pass
        raise AgentSessionError(
            "run_state_unknown", "Remote execution has not been confirmed terminal"
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, JsonValue] | None = None,
        params: dict[str, str | int] | None = None,
        allow_missing: bool = False,
    ) -> httpx.Response:
        try:
            response = await self._client.request(
                method, self._root.join(path), headers=self._headers, json=json, params=params
            )
        except httpx.RequestError as exc:
            raise AgentSessionError("runtime_unavailable", "Agent Runtime request failed") from exc
        if not (allow_missing and response.status_code == 404):
            _check_response(response)
        return response


def _check_response(response: httpx.Response) -> None:
    if response.status_code == 404:
        raise AgentSessionError("remote_session_not_found", "Remote Agent Session was not found")
    if not response.is_success:
        raise AgentSessionError("runtime_unavailable", "Agent Runtime rejected the request")


def _contract_error() -> AgentSessionError:
    return AgentSessionError(
        "runtime_contract_error", "Agent Runtime returned an invalid session contract"
    )


def _session_path(remote_session_id: str) -> str:
    if remote_session_id in {".", ".."}:
        raise _contract_error()
    return "api/sessions/" + quote(remote_session_id, safe="")


def _history_message(message: HermesHistoryMessage) -> AgentHistoryMessage:
    content: list[HistoryContent] = []
    if isinstance(message.content, str):
        content.append(HistoryText(text=message.content))
    elif isinstance(message.content, list):
        for block in message.content:
            if (
                isinstance(block, dict)
                and isinstance(block.get("type"), str)
                and block.get("type") in ("text", "input_text", "output_text")
            ):
                text = block.get("text")
                if isinstance(text, str):
                    content.append(HistoryText(text=text))
                    continue
            content_type = block.get("type") if isinstance(block, dict) else None
            content.append(
                HistoryUnsupportedContent(
                    content_type=content_type
                    if isinstance(content_type, str) and content_type
                    else "non_text"
                )
            )
    elif message.content is not None:
        content.append(HistoryUnsupportedContent(content_type="non_text"))
    for call in message.tool_calls or ():
        try:
            arguments = JSON_ARGUMENTS.validate_json(call.function.arguments)
        except ValidationError:
            content.append(HistoryUnsupportedContent(content_type="invalid_tool_arguments"))
        else:
            content.append(
                HistoryToolCall(
                    tool_call_id=call.id, tool_name=call.function.name, arguments=arguments
                )
            )
    role = message.role
    if role not in {"system", "developer", "user", "assistant", "tool"}:
        role = "unsupported"
        content.append(HistoryUnsupportedContent(content_type="unsupported_role"))
    return AgentHistoryMessage(
        message_id=str(message.id),
        role=cast(Literal["system", "developer", "user", "assistant", "tool", "unsupported"], role),
        content=tuple(content),
        tool_call_id=message.tool_call_id,
        tool_name=message.tool_name,
        created_at=(
            datetime.fromtimestamp(message.timestamp, timezone.utc)
            if message.timestamp is not None
            else None
        ),
    )
