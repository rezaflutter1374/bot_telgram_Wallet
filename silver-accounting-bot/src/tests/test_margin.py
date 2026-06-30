from __future__ import annotations

from decimal import Decimal

from domain.services.margin import MarginCalculator


def test_margin_required_deposit() -> None:
    calc = MarginCalculator(Decimal("100"), Decimal("1"))
    assert calc.required_deposit_usd(Decimal("0")) == Decimal("0")
    assert calc.required_deposit_usd(Decimal("1")) == Decimal("100.00")
    assert calc.required_deposit_usd(Decimal("2.5")) == Decimal("250.00")


def test_margin_snapshot_basic() -> None:
    calc = MarginCalculator(Decimal("100"), Decimal("1"))
    snap = calc.snapshot(
        available_balance_usd=Decimal("50"),
        frozen_balance_usd=Decimal("0"),
        floating_pnl_usd=Decimal("0"),
        exposure_kg=Decimal("0.5"),
    )
    assert snap.used_margin_usd == Decimal("50.00")
    assert snap.equity_usd == Decimal("50.00")
    assert snap.free_margin_usd == Decimal("0.00")
    assert snap.margin_ratio == Decimal("1.0000")


def test_margin_call_trigger() -> None:
    calc = MarginCalculator(Decimal("100"), Decimal("1"))
    snap = calc.snapshot(
        available_balance_usd=Decimal("49"),
        frozen_balance_usd=Decimal("0"),
        floating_pnl_usd=Decimal("0"),
        exposure_kg=Decimal("0.5"),
    )
    assert calc.is_margin_call(snap) is True


def test_margin_no_exposure_ratio_large() -> None:
    calc = MarginCalculator(Decimal("100"), Decimal("1"))
    snap = calc.snapshot(
        available_balance_usd=Decimal("1"),
        frozen_balance_usd=Decimal("0"),
        floating_pnl_usd=Decimal("0"),
        exposure_kg=Decimal("0"),
    )
    assert snap.used_margin_usd == Decimal("0")
    assert snap.margin_ratio > Decimal("1000")
