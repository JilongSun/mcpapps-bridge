"""Application-owned composition for bridge observation consumers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from mabrid.bridge import BridgeObservation, BridgeObserver


class BridgeSessionObserverFactory(Protocol):
    def create(self, session_key: str, endpoint_slug: str) -> BridgeObserver | None: ...


class CompositeBridgeSessionObserverFactory:
    def __init__(self, factories: Iterable[BridgeSessionObserverFactory]) -> None:
        self._factories = tuple(factories)
        if not self._factories:
            raise ValueError(
                "Composite bridge session observer factory requires at least one factory"
            )

    def create(self, session_key: str, endpoint_slug: str) -> BridgeObserver | None:
        observers = tuple(
            observer
            for factory in self._factories
            if (observer := factory.create(session_key, endpoint_slug)) is not None
        )
        if not observers:
            return None
        return CompositeBridgeObserver(observers)


class CompositeBridgeObserver:
    def __init__(self, observers: Iterable[BridgeObserver]) -> None:
        self._observers = tuple(observers)
        if not self._observers:
            raise ValueError("Composite bridge observer requires at least one observer")

    async def observe(self, event: BridgeObservation) -> None:
        for observer in self._observers:
            await observer.observe(event)
