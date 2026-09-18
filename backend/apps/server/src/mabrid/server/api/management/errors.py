"""RFC 9457 Problem Details used by management and readiness routes."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

PROBLEM_MEDIA_TYPE = "application/problem+json"


class ProblemDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str
    title: str
    status: int
    detail: str
    code: str


@dataclass(frozen=True)
class ManagementProblem(Exception):
    problem: ProblemDetails


def problem(
    *,
    code: str,
    title: str,
    status: int,
    detail: str,
) -> ProblemDetails:
    return ProblemDetails(
        type=f"urn:mabrid:problem:{code.replace('_', '-')}",
        title=title,
        status=status,
        detail=detail,
        code=code,
    )


def problem_response(details: ProblemDetails) -> JSONResponse:
    return JSONResponse(
        status_code=details.status,
        content=details.model_dump(mode="json"),
        media_type=PROBLEM_MEDIA_TYPE,
    )
