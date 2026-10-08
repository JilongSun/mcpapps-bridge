"""First-party Host HTTP schema drafts; no route or native runtime is registered here."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, NonNegativeInt


class HostHttpModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CreateHostSessionRequest(HostHttpModel):
    title: str | None = None


class HostSessionResponse(HostHttpModel):
    session_id: UUID
    target_id: str = Field(min_length=1)
    title: str | None = None
    created_at: AwareDatetime
    binding_state: Literal["unknown", "available", "missing", "runtime_changed", "unavailable"]


class HostSessionPageResponse(HostHttpModel):
    sessions: tuple[HostSessionResponse, ...]
    limit: int = Field(ge=1, le=200)
    offset: NonNegativeInt
    has_more: bool


class StartHostSessionRunRequest(HostHttpModel):
    input_text: str = Field(min_length=1, pattern=r"\S")


class HostErrorResponse(HostHttpModel):
    code: Literal[
        "session_not_found",
        "remote_session_not_found",
        "runtime_binding_changed",
        "runtime_unavailable",
        "runtime_contract_error",
        "target_busy",
        "unsupported_operation",
        "run_state_unknown",
    ]
    message: str
    session_id: UUID | None = None
    run_id: UUID | None = None
