from __future__ import annotations

from decimal import Decimal

from domain.services.arbitration import ArbitrationHandler, ArbitrationReason


def test_arbitration_compute_adjustment_from_price() -> None:
    handler = ArbitrationHandler()
    adj = handler.compute_adjustment(
        reason=ArbitrationReason.price_correction,
        old_price_usd=Decimal("100"),
        new_price_usd=Decimal("110"),
        quantity_kg=Decimal("10"),
    )
    assert adj == Decimal("100.00")


def test_arbitration_compute_adjustment_from_pnl() -> None:
    handler = ArbitrationHandler()
    adj = handler.compute_adjustment(
        reason=ArbitrationReason.trade_reversal,
        old_pnl_usd=Decimal("500"),
        new_pnl_usd=Decimal("300"),
    )
    assert adj == Decimal("-200.00")


def test_arbitration_compute_adjustment_zero() -> None:
    handler = ArbitrationHandler()
    adj = handler.compute_adjustment(
        reason=ArbitrationReason.supervisor_override,
        old_price_usd=Decimal("100"),
        new_price_usd=Decimal("200"),
        quantity_kg=Decimal("10"),
    )
    assert adj == Decimal("0")


def test_arbitration_validation_passes() -> None:
    handler = ArbitrationHandler()
    valid, err = handler.validate_arbitration_request(
        reason=ArbitrationReason.price_correction,
        old_price_usd=Decimal("100"),
        new_price_usd=Decimal("110"),
        notes="Correcting erroneous price due to provider glitch",
    )
    assert valid
    assert err is None


def test_arbitration_validation_fails_no_price() -> None:
    handler = ArbitrationHandler()
    valid, err = handler.validate_arbitration_request(
        reason=ArbitrationReason.price_correction,
        old_price_usd=None,
        new_price_usd=None,
        notes="Some notes here that are long enough",
    )
    assert not valid
    assert err is not None


def test_arbitration_validation_fails_short_notes() -> None:
    handler = ArbitrationHandler()
    valid, err = handler.validate_arbitration_request(
        reason=ArbitrationReason.system_error,
        old_price_usd=None,
        new_price_usd=None,
        notes="short",
    )
    assert not valid
    assert "notes" in (err or "").lower()


def test_arbitration_validation_settlement_adjustment_passes() -> None:
    handler = ArbitrationHandler()
    valid, err = handler.validate_arbitration_request(
        reason=ArbitrationReason.settlement_adjustment,
        old_price_usd=None,
        new_price_usd=None,
        notes="Adjusting settlement due to incorrect price feed at 01:25",
    )
    assert valid
    assert err is None
