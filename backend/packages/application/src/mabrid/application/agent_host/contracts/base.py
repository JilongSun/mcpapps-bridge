"""Shared validation policy for provider-neutral Agent Host contracts."""

from pydantic import BaseModel, ConfigDict


class AgentHostModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
