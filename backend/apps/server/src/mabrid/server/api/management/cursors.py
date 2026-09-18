"""Opaque HTTP cursor encoding for bridge session keysets."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Literal
from uuid import UUID

from mabrid.application.gateway.sessions import SessionKeyset
from pydantic import BaseModel, ConfigDict, ValidationError


class CursorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    v: Literal[1] = 1
    created_at: datetime
    session_id: UUID


def encode_session_cursor(keyset: SessionKeyset) -> str:
    payload = CursorPayload(
        created_at=keyset.created_at,
        session_id=keyset.session_id,
    ).model_dump_json()
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def decode_session_cursor(value: str) -> SessionKeyset:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        )
        payload = CursorPayload.model_validate_json(decoded)
        return SessionKeyset(
            created_at=payload.created_at,
            session_id=payload.session_id,
        )
    except (UnicodeDecodeError, ValueError, ValidationError, binascii.Error) as exc:
        raise ValueError("Invalid session cursor") from exc
