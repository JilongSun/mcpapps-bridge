"""Read-only Gateway management HTTP routes."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, Query
from mabrid.application.gateway.inspection import SessionEventPageRequest
from mabrid.application.gateway.sessions import BridgeSessionStatus, SessionPageRequest

from mabrid.server.composition import GatewayManagementComposition
from mabrid.server.logging import get_logger

from .cursors import decode_session_cursor, encode_session_cursor
from .dto import (
    GatewayStatusResponse,
    SequencedSessionEventResponse,
    SessionEventPageResponse,
    SessionPageResponse,
    SessionResponse,
    SessionSnapshotResponse,
    TopologyResponse,
)
from .errors import ManagementProblem, problem

logger = get_logger(__name__)


def create_gateway_management_router(
    management: GatewayManagementComposition,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/gateway", tags=["gateway-management"])

    @router.get("/status", response_model=GatewayStatusResponse)
    async def get_status() -> GatewayStatusResponse:
        slugs = management.published_endpoint_slugs
        return GatewayStatusResponse(
            version="0.1.0",
            advertised_base_url=management.advertised_base_url,
            published_endpoint_count=len(slugs),
            published_endpoint_slugs=slugs,
        )

    @router.get("/topology", response_model=TopologyResponse)
    async def get_topology() -> TopologyResponse:
        try:
            snapshot = await management.topology_reader.read_snapshot()
            return TopologyResponse.from_model(snapshot, management.advertised_base_url)
        except Exception as exc:
            _raise_internal_error("Unable to read the managed topology", exc)

    @router.get("/sessions", response_model=SessionPageResponse)
    async def list_sessions(
        endpoint_id: UUID | None = None,
        status: BridgeSessionStatus | None = None,
        cursor: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> SessionPageResponse:
        if cursor is not None:
            try:
                before = decode_session_cursor(cursor)
            except ValueError as exc:
                raise ManagementProblem(
                    problem(
                        code="invalid_cursor",
                        title="Invalid cursor",
                        status=400,
                        detail="The session cursor is malformed or unsupported.",
                    )
                ) from exc
        else:
            before = None
        try:
            page = await management.session_history_reader.list_sessions(
                SessionPageRequest(
                    endpoint_id=endpoint_id,
                    status=status,
                    before=before,
                    limit=limit,
                )
            )
            return SessionPageResponse(
                items=tuple(SessionResponse.from_model(item) for item in page.items),
                next_cursor=(
                    encode_session_cursor(page.next_keyset)
                    if page.next_keyset is not None
                    else None
                ),
            )
        except Exception as exc:
            _raise_internal_error("Unable to read bridge session history", exc)

    @router.get("/sessions/{session_id}", response_model=SessionResponse)
    async def get_session(session_id: UUID) -> SessionResponse:
        try:
            session = await management.session_history_reader.get_session(session_id)
        except Exception as exc:
            _raise_internal_error("Unable to read the bridge session", exc)
        if session is None:
            _raise_session_not_found(session_id)
        return SessionResponse.from_model(session)

    @router.get("/sessions/{session_id}/snapshot", response_model=SessionSnapshotResponse)
    async def get_session_snapshot(session_id: UUID) -> SessionSnapshotResponse:
        try:
            snapshot = await management.session_inspection_reader.get_snapshot(session_id)
        except Exception as exc:
            _raise_internal_error("Unable to read the bridge session snapshot", exc)
        if snapshot is None:
            _raise_session_not_found(session_id)
        return SessionSnapshotResponse.from_model(snapshot)

    @router.get("/sessions/{session_id}/events", response_model=SessionEventPageResponse)
    async def list_session_events(
        session_id: UUID,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> SessionEventPageResponse:
        try:
            page = await management.session_inspection_reader.list_events(
                SessionEventPageRequest(
                    session_id=session_id,
                    after=after,
                    limit=limit,
                )
            )
        except Exception as exc:
            _raise_internal_error("Unable to read bridge session events", exc)
        if page is None:
            _raise_session_not_found(session_id)
        return SessionEventPageResponse(
            items=tuple(SequencedSessionEventResponse.from_model(item) for item in page.items),
            next_after=page.next_after,
        )

    return router


def _raise_session_not_found(session_id: UUID) -> NoReturn:
    raise ManagementProblem(
        problem(
            code="session_not_found",
            title="Session not found",
            status=404,
            detail=f"Bridge session '{session_id}' was not found.",
        )
    )


def _raise_internal_error(detail: str, exc: Exception) -> NoReturn:
    logger.exception(detail, exc_info=exc)
    raise ManagementProblem(
        problem(
            code="internal_error",
            title="Internal server error",
            status=500,
            detail="The management request could not be completed.",
        )
    ) from exc
