"""Provider-neutral errors for session binding and runtime operations."""

from typing import Literal

SessionErrorCode = Literal[
    "session_not_found",
    "remote_session_not_found",
    "runtime_binding_changed",
    "runtime_unavailable",
    "runtime_contract_error",
    "run_state_unknown",
]


class AgentSessionError(RuntimeError):
    def __init__(self, code: SessionErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
