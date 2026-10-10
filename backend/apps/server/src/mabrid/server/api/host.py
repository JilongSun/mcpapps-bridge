"""First-party native Session HTTP adapters; application services own behavior."""

from typing import Annotated
from uuid import UUID
from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Any
import anyio

from fastapi import APIRouter, Query, Request
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from starlette.responses import Response
from fastapi.responses import JSONResponse

from mabrid.application.agent_host import (
    AgentSessionService,
    AgentSessionError,
    AgentSessionRecord,
    CreateAgentSessionCommand,
    HistoryPageQuery,
    AgentHistoryPage,
    StartSessionRunCommand,
    AgentRunConflictError,
    AgentRunStarted,
    AgentSessionRunStatus,
)
from mabrid.application.host import HostSessionEventStream, HostAgentEvent, HostEvent

from .host_contracts import (
    CreateHostSessionRequest,
    HostSessionResponse,
    HostSessionPageResponse,
    HostErrorResponse,
    StartHostSessionRunRequest,
    HostStopResponse,
    HostReconcileResponse,
)
from .host_stream import HostEventSourceResponse, close_presentation, project_host_event


ERRORS = {
    "run_not_found": (404, "Run was not found for this Agent Session."),
    "internal_error": (500, "The Host operation failed."),
    "session_not_found": (404, "Agent Session was not found."),
    "remote_session_not_found": (404, "The runtime conversation was not found."),
    "runtime_binding_changed": (409, "Agent Session belongs to another runtime deployment."),
    "runtime_unavailable": (503, "The Agent runtime is unavailable."),
    "runtime_contract_error": (502, "The Agent runtime returned an invalid response."),
    "target_busy": (409, "The Agent Target already has an active Run."),
    "unsupported_operation": (503, "This Host operation is not enabled or supported."),
    "run_state_unknown": (409, "Run settlement is unknown; overlapping execution is not allowed."),
    "invalid_request": (422, "The request parameters are invalid."),
}


def host_error(
    code: str, *, session_id: UUID | None = None, run_id: UUID | None = None
) -> HostErrorResponse:
    _, message = ERRORS.get(code, ERRORS["runtime_contract_error"])
    return HostErrorResponse.model_validate(
        {
            "code": code if code in ERRORS else "runtime_contract_error",
            "message": message,
            "session_id": session_id,
            "run_id": run_id,
        }
    )


def host_error_response(
    code: str, *, session_id: UUID | None = None, run_id: UUID | None = None
) -> JSONResponse:
    status, _ = ERRORS.get(code, ERRORS["runtime_contract_error"])
    return JSONResponse(
        status_code=status,
        content=host_error(code, session_id=session_id, run_id=run_id).model_dump(mode="json"),
    )


def _session_response(
    record: AgentSessionRecord,
    service: AgentSessionService,
    *,
    verified: bool = False,
    target_run: AgentSessionRunStatus | None = None,
) -> HostSessionResponse:
    return HostSessionResponse(
        session_id=record.session_id,
        target_id=record.target_id,
        title=record.title,
        created_at=record.created_at,
        binding_state="runtime_changed"
        if record.runtime_session.runtime_binding_id != service.runtime_binding_id
        else "available"
        if verified
        else "unknown",
        target_run=target_run,
    )


async def _admit(request: Request, source: AsyncGenerator[HostEvent, None]) -> HostEvent:
    first: HostEvent | None = None
    error: BaseException | None = None
    disconnected = False
    async with anyio.create_task_group() as tasks:

        async def prime() -> None:
            nonlocal first, error
            try:
                first = await anext(source)
            except BaseException as exc:
                error = exc
            finally:
                tasks.cancel_scope.cancel()

        async def listen() -> None:
            nonlocal disconnected
            while True:
                if (await request.receive())["type"] == "http.disconnect":
                    disconnected = True
                    tasks.cancel_scope.cancel()
                    return

        tasks.start_soon(prime)
        tasks.start_soon(listen)
    if disconnected:
        raise AgentSessionError("run_state_unknown", "Client disconnected during admission")
    if error is not None:
        raise error
    if first is None:
        raise AgentSessionError("runtime_contract_error", "Run admission produced no event")
    return first


class _HostRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError:
                raise
            except Exception:
                return host_error_response("internal_error")

        return guarded


def create_host_router(
    sessions: AgentSessionService | None, presentation: HostSessionEventStream | None = None
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/host",
        tags=["Host"],
        route_class=_HostRoute,
        responses={
            status: {"model": HostErrorResponse} for status in (404, 409, 422, 500, 502, 503)
        },
    )

    @router.post("/sessions", response_model=HostSessionResponse, status_code=201)
    async def create_session(payload: CreateHostSessionRequest):
        if sessions is None:
            return host_error_response("unsupported_operation")
        try:
            record = await sessions.create_session(CreateAgentSessionCommand(title=payload.title))
            return _session_response(
                record, sessions, verified=True, target_run=await sessions.get_target_run()
            )
        except AgentSessionError as exc:
            return host_error_response(exc.code)

    @router.get("/sessions", response_model=HostSessionPageResponse)
    async def list_sessions(
        limit: Annotated[int, Query(ge=1, le=200)] = 20, offset: Annotated[int, Query(ge=0)] = 0
    ):
        if sessions is None:
            return host_error_response("unsupported_operation")
        records = await sessions.list_sessions(limit=limit + 1, offset=offset)
        target_run = await sessions.get_target_run()
        return HostSessionPageResponse(
            sessions=tuple(
                _session_response(record, sessions, target_run=target_run)
                for record in records[:limit]
            ),
            limit=limit,
            offset=offset,
            has_more=len(records) > limit,
        )

    @router.get("/sessions/{session_id}", response_model=HostSessionResponse)
    async def get_session(session_id: UUID):
        if sessions is None:
            return host_error_response("unsupported_operation", session_id=session_id)
        try:
            record = await sessions.reopen_session(session_id)
            return _session_response(
                record, sessions, verified=True, target_run=await sessions.get_target_run()
            )
        except AgentSessionError as exc:
            return host_error_response(exc.code, session_id=session_id)

    @router.get("/sessions/{session_id}/history", response_model=AgentHistoryPage)
    async def get_history(
        session_id: UUID,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
        order: Annotated[str, Query(pattern="^(oldest|latest)$")] = "latest",
    ):
        if sessions is None:
            return host_error_response("unsupported_operation", session_id=session_id)
        try:
            return await sessions.read_history(
                session_id,
                HistoryPageQuery.model_validate({"limit": limit, "offset": offset, "order": order}),
            )
        except AgentSessionError as exc:
            return host_error_response(exc.code, session_id=session_id)

    @router.post(
        "/sessions/{session_id}/runs",
        response_class=Response,
        response_model=None,
        status_code=200,
        responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}},
    )
    async def start_run(session_id: UUID, payload: StartHostSessionRunRequest, request: Request):
        if sessions is None or presentation is None:
            return host_error_response("unsupported_operation", session_id=session_id)
        if request.headers.get("last-event-id"):
            return host_error_response("unsupported_operation", session_id=session_id)
        command = StartSessionRunCommand(session_id=session_id, input_text=payload.input_text)
        source = presentation.run_events(command)
        try:
            first = await _admit(request, source)
            if not isinstance(first, HostAgentEvent) or not isinstance(
                first.event, AgentRunStarted
            ):
                raise AgentSessionError(
                    "runtime_contract_error", "Presentation did not start a Run"
                )
            project_host_event(first)
            return HostEventSourceResponse(source, first, session_id, command.run_id)
        except BaseException as exc:
            cleanup_error = await close_presentation(source)
            if not isinstance(exc, Exception):
                raise
            code = (
                cleanup_error.code
                if cleanup_error is not None
                else exc.code
                if isinstance(exc, AgentSessionError)
                else "target_busy"
                if isinstance(exc, AgentRunConflictError)
                else "runtime_contract_error"
            )
            return host_error_response(code, session_id=session_id, run_id=command.run_id)

    @router.post(
        "/sessions/{session_id}/runs/{run_id}/cancel",
        response_model=HostStopResponse,
        status_code=202,
    )
    async def cancel_run(session_id: UUID, run_id: UUID):
        if sessions is None:
            return host_error_response(
                "unsupported_operation", session_id=session_id, run_id=run_id
            )
        try:
            receipt = await sessions.request_stop(run_id, session_id=session_id)
            return HostStopResponse(session_id=session_id, run_id=run_id, accepted=receipt.accepted)
        except AgentSessionError as exc:
            return host_error_response(exc.code, session_id=session_id, run_id=run_id)

    @router.post(
        "/sessions/{session_id}/runs/{run_id}/reconcile", response_model=HostReconcileResponse
    )
    async def reconcile_run(session_id: UUID, run_id: UUID):
        if sessions is None:
            return host_error_response(
                "unsupported_operation", session_id=session_id, run_id=run_id
            )
        try:
            settled = await sessions.reconcile_run(session_id=session_id, run_id=run_id)
            return HostReconcileResponse(session_id=session_id, run_id=run_id, settled=settled)
        except AgentSessionError as exc:
            return host_error_response(exc.code, session_id=session_id, run_id=run_id)

    return router
