from __future__ import annotations

import asyncio
import logging
import time
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable, Coroutine

from domain.event_bus import EventBus, EventHandler
from domain.events import DomainEvent

logger = logging.getLogger(__name__)


class EventHandlerRegistration:
    def __init__(
        self,
        handler: EventHandler,
        *,
        handler_name: str | None = None,
        max_retries: int = 3,
        retry_delay_seconds: float = 1.0,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.handler = handler
        self.handler_name = handler_name or getattr(handler, "__name__", str(handler))
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.timeout_seconds = timeout_seconds


class InMemoryEventBus(EventBus):
    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandlerRegistration]] = defaultdict(list)
        self._global_subscribers: list[EventHandlerRegistration] = []
        self._dead_letter_handler: Callable[[DomainEvent, str], Coroutine[None, None, None]] | None = None

    def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
        *,
        max_retries: int = 3,
        retry_delay_seconds: float = 1.0,
        timeout_seconds: float = 30.0,
    ) -> None:
        reg = EventHandlerRegistration(
            handler=handler,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
            timeout_seconds=timeout_seconds,
        )
        self._subscribers[event_type].append(reg)

    def subscribe_all(self, handler: EventHandler, *, max_retries: int = 3, retry_delay_seconds: float = 1.0) -> None:
        reg = EventHandlerRegistration(handler=handler, max_retries=max_retries, retry_delay_seconds=retry_delay_seconds)
        self._global_subscribers.append(reg)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        self._subscribers[event_type] = [r for r in self._subscribers[event_type] if r.handler != handler]

    def set_dead_letter_handler(self, handler: Callable[[DomainEvent, str], Coroutine[None, None, None]]) -> None:
        self._dead_letter_handler = handler

    async def publish(self, event: DomainEvent) -> None:
        handlers = list(self._subscribers.get(event.event_type, []))
        handlers.extend(self._global_subscribers)
        if not handlers:
            logger.debug("No handlers for event %s", event.event_type)
            return
        results = await asyncio.gather(
            *[self._dispatch(event, reg) for reg in handlers],
            return_exceptions=True,
        )
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Handler %s failed for event %s: %s", handlers[idx].handler_name, event.event_type, result)
                if self._dead_letter_handler is not None:
                    await self._dead_letter_handler(event, str(result))

    async def _dispatch(self, event: DomainEvent, reg: EventHandlerRegistration) -> None:
        last_error: Exception | None = None
        for attempt in range(reg.max_retries + 1):
            try:
                start = time.monotonic()
                await asyncio.wait_for(reg.handler(event), timeout=reg.timeout_seconds)
                elapsed = time.monotonic() - start
                if elapsed > 1.0:
                    logger.warning("Handler %s took %.2fs for %s", reg.handler_name, elapsed, event.event_type)
                return
            except asyncio.TimeoutError as e:
                last_error = e
                logger.warning("Handler %s timed out (attempt %d/%d) for %s", reg.handler_name, attempt + 1, reg.max_retries + 1, event.event_type)
            except Exception as e:
                last_error = e
                logger.warning("Handler %s failed (attempt %d/%d) for %s: %s", reg.handler_name, attempt + 1, reg.max_retries + 1, event.event_type, e)
            if attempt < reg.max_retries:
                await asyncio.sleep(reg.retry_delay_seconds * (2 ** attempt))
        if last_error is not None:
            raise last_error


class EventTracer:
    def __init__(self, bus: InMemoryEventBus) -> None:
        self._bus = bus
        self._traced: list[dict] = []

    async def _trace_handler(self, event: DomainEvent) -> None:
        self._traced.append({
            "event_id": event.event_id,
            "event_type": event.event_type,
            "category": event.category.value,
            "occurred_at": event.occurred_at.isoformat(),
            "aggregate_id": event.aggregate_id,
            "actor_user_id": event.actor_user_id,
            "payload": event.payload,
            "correlation_id": event.correlation_id,
        })

    def attach(self) -> None:
        self._bus.subscribe_all(self._trace_handler)

    @property
    def events(self) -> list[dict]:
        return list(self._traced)

    def clear(self) -> None:
        self._traced.clear()
