"""Stable attribution from one Gateway tool operation to an Agent Run."""

from uuid import UUID

from pydantic import Field

from .base import AgentHostModel


class OperationRunAttribution(AgentHostModel):
    run_id: UUID
    target_id: str = Field(min_length=1)
    session_key: str = Field(min_length=1)
    operation_key: str = Field(min_length=1)
