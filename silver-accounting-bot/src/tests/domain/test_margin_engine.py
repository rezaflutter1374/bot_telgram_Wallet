from __future__ import annotations

from decimal import Decimal

import pytest

from domain.enums import MarginMode
from domain.services.margin import MarginCalculator
from domain.services.margin_engine import MarginEngine


@pytest.fixture
def calculator() -> MarginCalculator:
    return MarginCalculator(
        deposit_requirement_per_kg_usd=Decimal("100"),
        maintenance_ratio_threshold=Decimal("1"),
    )


@pytest.fixture
def engine(calculator: MarginCalculator) -> MarginEngine:
    return MarginEngine(calculator)


class TestCalculateRequirements:
    def test_cross_margin_calculation(self, engine: MarginEngine):
        req = engine.calculate_requirements(
            exposure_kg=Decimal("10"),
            equity_usd=Decimal("2000"),
            margin_balance_usd=Decimal("1000"),
        )
        assert req.initial_margin_usd == Decimal("1000")
        assert req.maintenance_margin_usd == Decimal("1000")
        assert req.used_margin_usd == Decimal("2000")
        assert req.free_margin_usd == Decimal("0")
        assert req.margin_ratio == Decimal("1")

    def test_position_value_exceeds_equity(self, engine: MarginEngine):
        req = engine.calculate_requirements(
            exposure_kg=Decimal("20"),
            equity_usd=Decimal("500"),
            margin_balance_usd=Decimal("0"),
        )
        assert req.initial_margin_usd == Decimal("2000")
        assert req.used_margin_usd == Decimal("500")

    def test_zero_exposure(self, engine: MarginEngine):
        req = engine.calculate_requirements(
            exposure_kg=Decimal("0"),
            equity_usd=Decimal("1000"),
            margin_balance_usd=Decimal("0"),
        )
        assert req.used_margin_usd == Decimal("0")
        assert req.margin_ratio == Decimal("999999")

    def test_with_custom_leverage(self, engine: MarginEngine):
        req = engine.calculate_requirements(
            exposure_kg=Decimal("10"),
            equity_usd=Decimal("2000"),
            margin_balance_usd=Decimal("1000"),
            leverage=Decimal("3"),
        )
        assert req.initial_margin_usd == Decimal("1000")

    def test_with_custom_maintenance_ratio(self, engine: MarginEngine):
        req = engine.calculate_requirements(
            exposure_kg=Decimal("10"),
            equity_usd=Decimal("2000"),
            margin_balance_usd=Decimal("1000"),
            maintenance_ratio=Decimal("0.5"),
        )
        assert req.maintenance_margin_usd == Decimal("500")

    def test_large_exposure_no_equity(self, engine: MarginEngine):
        req = engine.calculate_requirements(
            exposure_kg=Decimal("100"),
            equity_usd=Decimal("0"),
            margin_balance_usd=Decimal("0"),
        )
        assert req.used_margin_usd == Decimal("0")
        assert req.margin_ratio == Decimal("999999")


class TestCalculateIsolatedMargin:
    def test_isolated_margin_long(self, engine: MarginEngine):
        state = engine.calculate_isolated_margin(
            position_net_kg=Decimal("10"),
            position_avg_price_usd=Decimal("100"),
            margin_allocated_usd=Decimal("1000"),
            leverage=Decimal("2"),
            mark_price_usd=Decimal("100"),
        )
        assert state.liquidation_price_usd == Decimal("50")

    def test_isolated_margin_short(self, engine: MarginEngine):
        state = engine.calculate_isolated_margin(
            position_net_kg=Decimal("-10"),
            position_avg_price_usd=Decimal("100"),
            margin_allocated_usd=Decimal("1000"),
            leverage=Decimal("2"),
            mark_price_usd=Decimal("100"),
        )
        assert state.liquidation_price_usd == Decimal("150")

    def test_zero_position(self, engine: MarginEngine):
        state = engine.calculate_isolated_margin(
            position_net_kg=Decimal("0"),
            position_avg_price_usd=Decimal("100"),
            margin_allocated_usd=Decimal("1000"),
            leverage=Decimal("2"),
            mark_price_usd=Decimal("100"),
        )
        assert state.liquidation_price_usd is None

    def test_leverage_10x_long(self, engine: MarginEngine):
        state = engine.calculate_isolated_margin(
            position_net_kg=Decimal("10"),
            position_avg_price_usd=Decimal("100"),
            margin_allocated_usd=Decimal("100"),
            leverage=Decimal("10"),
            mark_price_usd=Decimal("100"),
        )
        assert state.liquidation_price_usd == Decimal("90")

    def test_leverage_3x_short(self, engine: MarginEngine):
        state = engine.calculate_isolated_margin(
            position_net_kg=Decimal("-5"),
            position_avg_price_usd=Decimal("200"),
            margin_allocated_usd=Decimal("500"),
            leverage=Decimal("3"),
            mark_price_usd=Decimal("200"),
        )
        expected_liq = Decimal("200") * (Decimal("1") + Decimal("1") / Decimal("3"))
        assert state.liquidation_price_usd == expected_liq.quantize(Decimal("0.000001"))

    def test_leverage_zero(self, engine: MarginEngine):
        state = engine.calculate_isolated_margin(
            position_net_kg=Decimal("10"),
            position_avg_price_usd=Decimal("100"),
            margin_allocated_usd=Decimal("1000"),
            leverage=Decimal("0"),
            mark_price_usd=Decimal("100"),
        )
        assert state.liquidation_price_usd is None


class TestCalculateFundingFee:
    def test_long_position_funding(self, engine: MarginEngine):
        fee = engine.calculate_funding_fee(
            position_net_kg=Decimal("10"),
            mark_price_usd=Decimal("100"),
            funding_rate=Decimal("0.001"),
        )
        assert fee == Decimal("1")

    def test_short_position_funding(self, engine: MarginEngine):
        fee = engine.calculate_funding_fee(
            position_net_kg=Decimal("-10"),
            mark_price_usd=Decimal("100"),
            funding_rate=Decimal("0.001"),
        )
        assert fee == Decimal("-1")

    def test_zero_position(self, engine: MarginEngine):
        fee = engine.calculate_funding_fee(
            position_net_kg=Decimal("0"),
            mark_price_usd=Decimal("100"),
            funding_rate=Decimal("0.001"),
        )
        assert fee == Decimal("0")

    def test_zero_rate(self, engine: MarginEngine):
        fee = engine.calculate_funding_fee(
            position_net_kg=Decimal("10"),
            mark_price_usd=Decimal("100"),
            funding_rate=Decimal("0"),
        )
        assert fee == Decimal("0")


class TestValidateMarginSufficient:
    def test_sufficient_margin_passes(self, engine: MarginEngine):
        ok, msg = engine.validate_margin_sufficient(
            required_margin_usd=Decimal("500"),
            available_balance_usd=Decimal("300"),
            frozen_balance_usd=Decimal("200"),
            margin_balance_usd=Decimal("100"),
        )
        assert ok is True
        assert msg == ""

    def test_insufficient_margin_fails(self, engine: MarginEngine):
        ok, msg = engine.validate_margin_sufficient(
            required_margin_usd=Decimal("1000"),
            available_balance_usd=Decimal("300"),
            frozen_balance_usd=Decimal("200"),
            margin_balance_usd=Decimal("100"),
        )
        assert ok is False
        assert "Insufficient margin" in msg

    def test_exact_margin_passes(self, engine: MarginEngine):
        ok, msg = engine.validate_margin_sufficient(
            required_margin_usd=Decimal("600"),
            available_balance_usd=Decimal("300"),
            frozen_balance_usd=Decimal("200"),
            margin_balance_usd=Decimal("100"),
        )
        assert ok is True

    def test_no_balance_available(self, engine: MarginEngine):
        ok, msg = engine.validate_margin_sufficient(
            required_margin_usd=Decimal("1"),
            available_balance_usd=Decimal("0"),
            frozen_balance_usd=Decimal("0"),
            margin_balance_usd=Decimal("0"),
        )
        assert ok is False





class TestMarginCallAndLiquidation:
    def test_margin_call_ratio_above_threshold(self, engine: MarginEngine, calculator: MarginCalculator):
        snap = calculator.snapshot(
            available_balance_usd=Decimal("2000"),
            frozen_balance_usd=Decimal("0"),
            floating_pnl_usd=Decimal("0"),
            exposure_kg=Decimal("10"),
        )
        ratio = engine.margin_call_ratio(snap)
        assert ratio >= Decimal("1")

    def test_is_margin_call_above_threshold(self, engine: MarginEngine, calculator: MarginCalculator):
        snap = calculator.snapshot(
            available_balance_usd=Decimal("2000"),
            frozen_balance_usd=Decimal("0"),
            floating_pnl_usd=Decimal("0"),
            exposure_kg=Decimal("10"),
        )
        assert engine.is_margin_call(snap, threshold=Decimal("1")) is False

    def test_is_margin_call_below_threshold(self, engine: MarginEngine, calculator: MarginCalculator):
        snap = calculator.snapshot(
            available_balance_usd=Decimal("500"),
            frozen_balance_usd=Decimal("0"),
            floating_pnl_usd=Decimal("0"),
            exposure_kg=Decimal("10"),
        )
        assert engine.is_margin_call(snap, threshold=Decimal("1")) is True

    def test_is_liquidation_above_threshold(self, engine: MarginEngine, calculator: MarginCalculator):
        snap = calculator.snapshot(
            available_balance_usd=Decimal("2000"),
            frozen_balance_usd=Decimal("0"),
            floating_pnl_usd=Decimal("0"),
            exposure_kg=Decimal("10"),
        )
        assert engine.is_liquidation(snap, threshold=Decimal("0.5")) is False

    def test_is_liquidation_below_threshold(self, engine: MarginEngine, calculator: MarginCalculator):
        snap = calculator.snapshot(
            available_balance_usd=Decimal("300"),
            frozen_balance_usd=Decimal("0"),
            floating_pnl_usd=Decimal("0"),
            exposure_kg=Decimal("10"),
        )
        assert engine.is_liquidation(snap, threshold=Decimal("0.5")) is True

    def test_margin_call_at_exact_threshold(self, engine: MarginEngine, calculator: MarginCalculator):
        snap = calculator.snapshot(
            available_balance_usd=Decimal("1000"),
            frozen_balance_usd=Decimal("0"),
            floating_pnl_usd=Decimal("0"),
            exposure_kg=Decimal("10"),
        )
        assert engine.is_margin_call(snap, threshold=Decimal("1")) is False

    def test_liquidation_at_exact_threshold(self, engine: MarginEngine, calculator: MarginCalculator):
        snap = calculator.snapshot(
            available_balance_usd=Decimal("500"),
            frozen_balance_usd=Decimal("0"),
            floating_pnl_usd=Decimal("0"),
            exposure_kg=Decimal("10"),
        )
        assert engine.is_liquidation(snap, threshold=Decimal("0.5")) is False

    def test_zero_maintenance_margin_ratio(self, engine: MarginEngine, calculator: MarginCalculator):
        snap = calculator.snapshot(
            available_balance_usd=Decimal("0"),
            frozen_balance_usd=Decimal("0"),
            floating_pnl_usd=Decimal("0"),
            exposure_kg=Decimal("0"),
        )
        ratio = engine.margin_call_ratio(snap)
        assert ratio == Decimal("999999")
