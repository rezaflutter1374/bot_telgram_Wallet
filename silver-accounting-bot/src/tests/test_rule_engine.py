from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from domain.enums import OrderStatus, OrderTimeInForce, OrderType, SettlementMode
from domain.services.rule_engine import (
    BusinessRuleEngine,
    OrderValidationRequest,
    RuleCategory,
    RuleResult,
)


def test_order_validation_passes() -> None:
    engine = BusinessRuleEngine()
    req = OrderValidationRequest(
        side="buy",
        order_type=OrderType.market,
        quantity_kg=Decimal("10"),
        limit_price=None,
        time_in_force=OrderTimeInForce.gtc,
        stop_price=None,
        post_only=False,
        reduce_only=False,
        user_kyc_status="approved",
        user_active_violations=0,
        current_exposure_kg=Decimal("0"),
        current_margin_ratio=Decimal("2"),
    )
    results = engine.validate_order(req)
    errors = [r for r in results if not r.passed]
    assert len(errors) == 0, f"Expected no errors, got: {errors}"


def test_order_validation_rejects_zero_quantity() -> None:
    engine = BusinessRuleEngine()
    req = OrderValidationRequest(
        side="buy",
        order_type=OrderType.market,
        quantity_kg=Decimal("0"),
        limit_price=None,
        time_in_force=OrderTimeInForce.gtc,
        stop_price=None,
        post_only=False,
        reduce_only=False,
        user_kyc_status="approved",
        user_active_violations=0,
        current_exposure_kg=Decimal("0"),
        current_margin_ratio=Decimal("2"),
    )
    results = engine.validate_order(req)
    errors = [r for r in results if not r.passed]
    assert any("order_quantity_positive" in e.rule_name for e in errors)


def test_order_validation_rejects_no_kyc() -> None:
    engine = BusinessRuleEngine()
    req = OrderValidationRequest(
        side="buy",
        order_type=OrderType.market,
        quantity_kg=Decimal("1"),
        limit_price=None,
        time_in_force=OrderTimeInForce.gtc,
        stop_price=None,
        post_only=False,
        reduce_only=False,
        user_kyc_status="rejected",
        user_active_violations=0,
        current_exposure_kg=Decimal("0"),
        current_margin_ratio=Decimal("2"),
    )
    results = engine.validate_order(req)
    errors = [r for r in results if not r.passed]
    assert any("kyc_required" in e.rule_name for e in errors)


def test_order_validation_rejects_low_margin() -> None:
    engine = BusinessRuleEngine()
    req = OrderValidationRequest(
        side="sell",
        order_type=OrderType.limit,
        quantity_kg=Decimal("5"),
        limit_price=Decimal("100"),
        time_in_force=OrderTimeInForce.gtc,
        stop_price=None,
        post_only=True,
        reduce_only=False,
        user_kyc_status="approved",
        user_active_violations=0,
        current_exposure_kg=Decimal("0"),
        current_margin_ratio=Decimal("0.3"),
    )
    results = engine.validate_order(req)
    errors = [r for r in results if not r.passed]
    assert any("margin_liquidation_threshold" in e.rule_name for e in errors)


def test_order_validation_rejects_too_many_violations() -> None:
    engine = BusinessRuleEngine()
    req = OrderValidationRequest(
        side="buy",
        order_type=OrderType.market,
        quantity_kg=Decimal("1"),
        limit_price=None,
        time_in_force=OrderTimeInForce.gtc,
        stop_price=None,
        post_only=False,
        reduce_only=False,
        user_kyc_status="approved",
        user_active_violations=5,
        current_exposure_kg=Decimal("0"),
        current_margin_ratio=Decimal("2"),
    )
    results = engine.validate_order(req)
    errors = [r for r in results if not r.passed]
    assert any("too_many_active_violations" in e.rule_name for e in errors)


def test_cancellation_validation() -> None:
    engine = BusinessRuleEngine()
    r1 = engine.validate_cancellation(OrderStatus.open)
    assert r1.passed
    r2 = engine.validate_cancellation(OrderStatus.cancelled)
    assert not r2.passed
    r3 = engine.validate_cancellation(OrderStatus.settled)
    assert not r3.passed


def test_settlement_time() -> None:
    engine = BusinessRuleEngine()
    afghan_tz = timezone(timedelta(hours=4, minutes=30))
    valid = datetime(2025, 1, 1, 1, 25, tzinfo=afghan_tz)
    assert engine.is_settlement_time(valid)
    invalid = datetime(2025, 1, 1, 10, 0, tzinfo=afghan_tz)
    assert not engine.is_settlement_time(invalid)


def test_next_settlement_time() -> None:
    engine = BusinessRuleEngine()
    afghan_tz = timezone(timedelta(hours=4, minutes=30))
    before = datetime(2025, 1, 1, 0, 0, tzinfo=afghan_tz)
    next_time = engine.next_settlement_time(before)
    assert next_time.hour == 1
    assert next_time.minute == 25
    assert next_time > before


def test_order_expiry() -> None:
    engine = BusinessRuleEngine()
    fresh = datetime.now(timezone.utc) - timedelta(seconds=10)
    assert not engine.order_has_expired(fresh)
    old = datetime.now(timezone.utc) - timedelta(seconds=120)
    assert engine.order_has_expired(old)
    expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    assert engine.order_has_expired(datetime.now(timezone.utc) - timedelta(hours=1), expires_at)


def test_settlement_mode_validation() -> None:
    engine = BusinessRuleEngine()
    r1 = engine.validate_settlement_mode("daily")
    assert r1.passed
    r2 = engine.validate_settlement_mode("invalid")
    assert not r2.passed


def test_supervisor_override_validation() -> None:
    engine = BusinessRuleEngine()
    r1 = engine.validate_supervisor_override("admin", "This is a valid override reason")
    assert r1.passed
    r2 = engine.validate_supervisor_override("guest", "reason")
    assert not r2.passed
    r3 = engine.validate_supervisor_override("super_admin", "short")
    assert not r3.passed


def test_mutual_cancellation() -> None:
    engine = BusinessRuleEngine()
    r1 = engine.validate_mutual_cancellation(OrderStatus.open, True)
    assert r1.passed
    r2 = engine.validate_mutual_cancellation(OrderStatus.completed, True)
    assert not r2.passed
    r3 = engine.validate_mutual_cancellation(OrderStatus.open, False)
    assert not r3.passed


def test_status_transitions_valid() -> None:
    engine = BusinessRuleEngine()
    assert engine.allowed_order_status_transition(OrderStatus.open, OrderStatus.filled).passed
    assert engine.allowed_order_status_transition(OrderStatus.filled, OrderStatus.settled).passed
    assert engine.allowed_order_status_transition(OrderStatus.completed, OrderStatus.settled).passed
    assert engine.allowed_order_status_transition(OrderStatus.pending, OrderStatus.open).passed


def test_status_transitions_invalid() -> None:
    engine = BusinessRuleEngine()
    r1 = engine.allowed_order_status_transition(OrderStatus.settled, OrderStatus.open)
    assert not r1.passed
    r2 = engine.allowed_order_status_transition(OrderStatus.cancelled, OrderStatus.filled)
    assert not r2.passed
    r3 = engine.allowed_order_status_transition(OrderStatus.pending, OrderStatus.settled)
    assert not r3.passed


def test_enum_can_transition_to() -> None:
    assert OrderStatus.open.can_transition_to(OrderStatus.filled)
    assert OrderStatus.filled.can_transition_to(OrderStatus.settled)
    assert not OrderStatus.settled.can_transition_to(OrderStatus.open)
    assert not OrderStatus.cancelled.can_transition_to(OrderStatus.filled)
    assert OrderStatus.pending.can_transition_to(OrderStatus.open)
    assert OrderStatus.partially_filled.can_transition_to(OrderStatus.filled)
    assert OrderStatus.filled.can_transition_to(OrderStatus.cancelled)
