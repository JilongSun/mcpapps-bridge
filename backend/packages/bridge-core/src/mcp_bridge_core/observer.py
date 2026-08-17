"""Observer port for application-owned bridge event handling."""

from __future__ import annotations

from typing import Protocol

from .observations import BridgeObservation


class BridgeObserver(Protocol):
    async def observe(self, event: BridgeObservation) -> None: ...


class NoOpBridgeObserver:
    async def observe(self, event: BridgeObservation) -> None:
        return None
