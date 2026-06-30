from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from domain.events import (
    DomainEvent,
    EventCategory,
    FinancialPeriodClosed,
    KycStatusChanged,
    OrderCreated,
    OrderFilled,
    OrderSettled,
    PaymentApproved,
    PaymentRejected,
    PriceUpdated,
    SettlementExecuted,
    SettlementRolledBack,
)
from infrastructure.event_bus.bus import EventTracer, InMemoryEventBus


@pytest.mark.asyncio
async def test_publish_no_handlers() -> None:
    bus = InMemoryEventBus()
    event = OrderCreated(aggregate_id="1", aggregate_type="order", actor_user_id=1, payload={"side": "buy"})
    await bus.publish(event)


@pytest.mark.asyncio
async def test_publish_single_handler() -> None:
    bus = InMemoryEventBus()
    received: list[DomainEvent] = []

    async def handler(event: DomainEvent) -> None:
        received.append(event)

    bus.subscribe("order.created", handler)
    event = OrderCreated(aggregate_id="1", aggregate_type="order", actor_user_id=1, payload={})
    await bus.publish(event)
    assert len(received) == 1
    assert received[0].event_type == "order.created"
    assert received[0].aggregate_id == "1"


@pytest.mark.asyncio
async def test_publish_multiple_handlers() -> None:
    bus = InMemoryEventBus()
    results: list[str] = []

    async def h1(event: DomainEvent) -> None:
        results.append("h1")

    async def h2(event: DomainEvent) -> None:
        results.append("h2")

    bus.subscribe("order.created", h1)
    bus.subscribe("order.created", h2)
    await bus.publish(OrderCreated(aggregate_id="1", aggregate_type="order", actor_user_id=1, payload={}))
    assert len(results) == 2
    assert "h1" in results
    assert "h2" in results


@pytest.mark.asyncio
async def test_subscribe_all() -> None:
    bus = InMemoryEventBus()
    received: list[DomainEvent] = []

    async def handler(event: DomainEvent) -> None:
        received.append(event)

    bus.subscribe_all(handler)
    await bus.publish(OrderCreated(aggregate_id="1", aggregate_type="order", actor_user_id=1, payload={}))
    await bus.publish(PriceUpdated(aggregate_id="2", aggregate_type="price", actor_user_id=2, payload={}))
    assert len(received) == 2


@pytest.mark.asyncio
async def test_unsubscribe() -> None:
    bus = InMemoryEventBus()
    received: list[DomainEvent] = []

    async def handler(event: DomainEvent) -> None:
        received.append(event)

    bus.subscribe("order.created", handler)
    bus.unsubscribe("order.created", handler)
    await bus.publish(OrderCreated(aggregate_id="1", aggregate_type="order", actor_user_id=1, payload={}))
    assert len(received) == 0


@pytest.mark.asyncio
async def test_retry_on_failure() -> None:
    bus = InMemoryEventBus()
    attempt_count = 0

    async def failing_handler(event: DomainEvent) -> None:
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 2:
            raise RuntimeError("Temporary failure")

    bus.subscribe("order.created", failing_handler, max_retries=2, retry_delay_seconds=0.01)
    await bus.publish(OrderCreated(aggregate_id="1", aggregate_type="order", actor_user_id=1, payload={}))
    assert attempt_count == 2


@pytest.mark.asyncio
async def test_dead_letter_on_max_retries() -> None:
    bus = InMemoryEventBus()
    dead_letter_events: list[tuple[DomainEvent, str]] = []

    async def dead_handler(event: DomainEvent, error: str) -> None:
        dead_letter_events.append((event, error))

    bus.set_dead_letter_handler(dead_handler)

    async def always_fails(event: DomainEvent) -> None:
        raise RuntimeError("Always fails")

    bus.subscribe("order.created", always_fails, max_retries=1, retry_delay_seconds=0.01)
    await bus.publish(OrderCreated(aggregate_id="1", aggregate_type="order", actor_user_id=1, payload={}))
    assert len(dead_letter_events) == 1


@pytest.mark.asyncio
async def test_event_tracer() -> None:
    bus = InMemoryEventBus()
    tracer = EventTracer(bus)
    tracer.attach()

    await bus.publish(OrderCreated(aggregate_id="1", aggregate_type="order", actor_user_id=1, payload={"side": "buy"}))
    await bus.publish(PriceUpdated(aggregate_id="2", aggregate_type="price", actor_user_id=2, payload={"price": "100"}))

    assert len(tracer.events) == 2
    assert tracer.events[0]["event_type"] == "order.created"
    assert tracer.events[1]["event_type"] == "price.updated"


@pytest.mark.asyncio
async def test_event_has_correlation_id() -> None:
    bus = InMemoryEventBus()
    received: list[DomainEvent] = []

    async def handler(event: DomainEvent) -> None:
        received.append(event)

    bus.subscribe("order.created", handler)
    event = OrderCreated(
        aggregate_id="1",
        aggregate_type="order",
        actor_user_id=1,
        payload={},
        correlation_id="corr-123",
        causation_id="cause-456",
    )
    await bus.publish(event)
    assert received[0].correlation_id == "corr-123"
    assert received[0].causation_id == "cause-456"


@pytest.mark.asyncio
async def test_domain_event_defaults() -> None:
    event = OrderCreated(aggregate_id="1", aggregate_type="order", actor_user_id=1, payload={"qty": "10"})
    assert event.event_id is not None
    assert event.category == EventCategory.order
    assert event.version.value == "1"
    assert event.occurred_at is not None


@pytest.mark.asyncio
async def test_all_event_types() -> None:
    events = [
        OrderCreated(aggregate_id="1", aggregate_type="order", actor_user_id=1, payload={}),
        OrderFilled(aggregate_id="1", aggregate_type="order", actor_user_id=1, payload={}),
        OrderSettled(aggregate_id="1", aggregate_type="order", actor_user_id=1, payload={}),
        SettlementExecuted(aggregate_id="1", aggregate_type="settlement", actor_user_id=1, payload={}),
        SettlementRolledBack(aggregate_id="1", aggregate_type="settlement", actor_user_id=1, payload={}),
        PaymentApproved(aggregate_id="1", aggregate_type="payment", actor_user_id=1, payload={}),
        PaymentRejected(aggregate_id="1", aggregate_type="payment", actor_user_id=1, payload={}),
        KycStatusChanged(aggregate_id="1", aggregate_type="user", actor_user_id=1, payload={}),
        PriceUpdated(aggregate_id="1", aggregate_type="price", actor_user_id=1, payload={}),
        FinancialPeriodClosed(aggregate_id="1", aggregate_type="financial_period", actor_user_id=1, payload={}),
    ]
    assert len(events) == 10
    for e in events:
        assert e.event_id is not None
        assert e.event_type != ""


@pytest.mark.asyncio
async def test_concurrent_publish() -> None:
    bus = InMemoryEventBus()
    counter = 0

    async def slow_handler(event: DomainEvent) -> None:
        nonlocal counter
        await asyncio.sleep(0.01)
        counter += 1

    bus.subscribe("order.created", slow_handler, max_retries=0)
    tasks = [bus.publish(OrderCreated(aggregate_id=str(i), aggregate_type="order", actor_user_id=1, payload={})) for i in range(10)]
    await asyncio.gather(*tasks)
    assert counter == 10


@pytest.mark.asyncio
async def test_timeout_handler() -> None:
    bus = InMemoryEventBus()
    dead_letter_events: list[tuple[DomainEvent, str]] = []

    async def dead_handler(event: DomainEvent, error: str) -> None:
        dead_letter_events.append((event, error))

    bus.set_dead_letter_handler(dead_handler)

    async def slow_handler(event: DomainEvent) -> None:
        await asyncio.sleep(10)

    bus.subscribe("order.created", slow_handler, max_retries=0, timeout_seconds=0.05, retry_delay_seconds=0.01)
    await bus.publish(OrderCreated(aggregate_id="1", aggregate_type="order", actor_user_id=1, payload={}))
    assert len(dead_letter_events) == 1
