from __future__ import annotations

from typing import Callable, Coroutine, Protocol

from domain.events import DomainEvent


EventHandler = Callable[[DomainEvent], Coroutine[None, None, None]]


class EventBus(Protocol):
    async def publish(self, event: DomainEvent) -> None: ...

    def subscribe(self, event_type: str, handler: EventHandler) -> None: ...

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None: ...


EventFilter = Callable[[DomainEvent], bool]
