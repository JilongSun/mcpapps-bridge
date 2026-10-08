"""Hermes native session, history, and Run control wire documents."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, NonNegativeInt


class HermesSessionWireModel(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)


class HermesSession(HermesSessionWireModel):
    id: str = Field(min_length=1)
    title: str | None = None
    started_at: float | None = None


class HermesSessionDocument(HermesSessionWireModel):
    object: Literal["hermes.session"]
    session: HermesSession


class HermesToolFunction(HermesSessionWireModel):
    name: str = Field(min_length=1)
    arguments: str


class HermesToolCall(HermesSessionWireModel):
    id: str = Field(min_length=1)
    type: Literal["function"]
    function: HermesToolFunction


class HermesHistoryMessage(HermesSessionWireModel):
    id: int | str
    role: str
    content: JsonValue
    tool_calls: tuple[HermesToolCall, ...] | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    timestamp: float | None = None


class HermesHistoryPagination(HermesSessionWireModel):
    limit: int = Field(ge=0, le=500)
    offset: NonNegativeInt
    order: Literal["oldest", "latest"]
    returned: NonNegativeInt


class HermesHistoryDocument(HermesSessionWireModel):
    object: Literal["list"]
    session_id: str = Field(min_length=1)
    data: tuple[HermesHistoryMessage, ...]
    pagination: HermesHistoryPagination


class HermesSessionChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    message: str = Field(min_length=1, pattern=r"\S")


class HermesSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    title: str | None = None


class HermesRunStatusDocument(HermesSessionWireModel):
    run_id: str = Field(min_length=1)
    status: Literal["queued", "running", "stopping", "completed", "failed", "cancelled"]
    session_id: str | None = None


class HermesStopDocument(HermesSessionWireModel):
    run_id: str = Field(min_length=1)
    status: Literal["stopping"]
