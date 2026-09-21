"""Application-owned composition for bridge observation consumers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from mabrid.bridge import BridgeObservation, BridgeObserver


class BridgeSessionObserverFactory(Protocol):
    def create(self, session_key: str, endpoint_slug: str) -> BridgeObserver | None: ...


class CompositeBridgeObserver:
    def __init__(self, observers: Iterable[BridgeObserver]) -> None:
        self._observers = tuple(observers)
        if not self._observers:
            raise ValueError("Composite bridge observer requires at least one observer")

    async def observe(self, event: BridgeObservation) -> None:
        for observer in self._observers:
            await observer.observe(event)
