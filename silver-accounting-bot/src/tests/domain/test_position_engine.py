from __future__ import annotations

from decimal import Decimal

import pytest

from domain.services.position_engine import PositionEngine


@pytest.fixture
def engine() -> PositionEngine:
    return PositionEngine()


class TestApplyTrade:
    def test_opening_long_position(self, engine: PositionEngine):
        change = engine.apply_trade(
            current_net_kg=Decimal("0"),
            current_avg_price=Decimal("0"),
            current_realized_pnl=Decimal("0"),
            side="buy",
            quantity_kg=Decimal("10"),
            price_usd=Decimal("100"),
        )
        assert change.new_net_kg == Decimal("10")
        assert change.new_avg_price_usd == Decimal("100")
        assert change.is_buy is True
        assert change.is_reduce is False
        assert change.realized_pnl_usd == Decimal("0")

    def test_opening_short_position(self, engine: PositionEngine):
        change = engine.apply_trade(
            current_net_kg=Decimal("0"),
            current_avg_price=Decimal("0"),
            current_realized_pnl=Decimal("0"),
            side="sell",
            quantity_kg=Decimal("5"),
            price_usd=Decimal("200"),
        )
        assert change.new_net_kg == Decimal("-5")
        assert change.new_avg_price_usd == Decimal("200")
        assert change.is_buy is False
        assert change.is_reduce is False

    def test_increasing_long_position(self, engine: PositionEngine):
        change = engine.apply_trade(
            current_net_kg=Decimal("10"),
            current_avg_price=Decimal("100"),
            current_realized_pnl=Decimal("0"),
            side="buy",
            quantity_kg=Decimal("10"),
            price_usd=Decimal("150"),
        )
        assert change.new_net_kg == Decimal("20")
        assert change.new_avg_price_usd == Decimal("125")
        assert change.is_reduce is False

    def test_increasing_short_position(self, engine: PositionEngine):
        change = engine.apply_trade(
            current_net_kg=Decimal("-5"),
            current_avg_price=Decimal("200"),
            current_realized_pnl=Decimal("0"),
            side="sell",
            quantity_kg=Decimal("5"),
            price_usd=Decimal("100"),
        )
        assert change.new_net_kg == Decimal("-10")
        assert change.new_avg_price_usd == Decimal("150")
        assert change.is_reduce is False

    def test_reducing_long_position(self, engine: PositionEngine):
        change = engine.apply_trade(
            current_net_kg=Decimal("10"),
            current_avg_price=Decimal("100"),
            current_realized_pnl=Decimal("0"),
            side="sell",
            quantity_kg=Decimal("4"),
            price_usd=Decimal("150"),
        )
        assert change.new_net_kg == Decimal("6")
        assert change.is_reduce is True
        assert change.new_avg_price_usd == Decimal("100")
        expected_pnl = (Decimal("4") * Decimal("150")) - (Decimal("4") * Decimal("100"))
        assert change.realized_pnl_usd == Decimal(expected_pnl).quantize(Decimal("0.01"))

    def test_reducing_short_position(self, engine: PositionEngine):
        change = engine.apply_trade(
            current_net_kg=Decimal("-10"),
            current_avg_price=Decimal("200"),
            current_realized_pnl=Decimal("0"),
            side="buy",
            quantity_kg=Decimal("4"),
            price_usd=Decimal("150"),
        )
        assert change.new_net_kg == Decimal("-6")
        assert change.is_reduce is True
        expected_pnl = (Decimal("4") * Decimal("200")) - (Decimal("4") * Decimal("150"))
        assert change.realized_pnl_usd == Decimal(expected_pnl).quantize(Decimal("0.01"))

    def test_closing_position_completely(self, engine: PositionEngine):
        change = engine.apply_trade(
            current_net_kg=Decimal("10"),
            current_avg_price=Decimal("100"),
            current_realized_pnl=Decimal("0"),
            side="sell",
            quantity_kg=Decimal("10"),
            price_usd=Decimal("150"),
        )
        assert change.new_net_kg == Decimal("0")
        assert change.is_reduce is True
        expected_pnl = (Decimal("10") * Decimal("150")) - (Decimal("10") * Decimal("100"))
        assert change.realized_pnl_usd == Decimal(expected_pnl).quantize(Decimal("0.01"))

    def test_reversing_long_to_short(self, engine: PositionEngine):
        change = engine.apply_trade(
            current_net_kg=Decimal("10"),
            current_avg_price=Decimal("100"),
            current_realized_pnl=Decimal("0"),
            side="sell",
            quantity_kg=Decimal("15"),
            price_usd=Decimal("150"),
        )
        assert change.new_net_kg == Decimal("-5")
        assert change.is_reduce is True
        expected_pnl = (Decimal("10") * Decimal("150")) - (Decimal("10") * Decimal("100"))
        assert change.realized_pnl_usd == Decimal(expected_pnl).quantize(Decimal("0.01"))

    def test_reversing_short_to_long(self, engine: PositionEngine):
        change = engine.apply_trade(
            current_net_kg=Decimal("-10"),
            current_avg_price=Decimal("200"),
            current_realized_pnl=Decimal("0"),
            side="buy",
            quantity_kg=Decimal("15"),
            price_usd=Decimal("150"),
        )
        assert change.new_net_kg == Decimal("5")

    def test_zero_quantity_noop(self, engine: PositionEngine):
        change = engine.apply_trade(
            current_net_kg=Decimal("10"),
            current_avg_price=Decimal("100"),
            current_realized_pnl=Decimal("0"),
            side="buy",
            quantity_kg=Decimal("0"),
            price_usd=Decimal("150"),
        )
        assert change.new_net_kg == Decimal("10")
        assert change.realized_pnl_usd == Decimal("0")

    def test_reducing_with_fee(self, engine: PositionEngine):
        change = engine.apply_trade(
            current_net_kg=Decimal("10"),
            current_avg_price=Decimal("100"),
            current_realized_pnl=Decimal("0"),
            side="sell",
            quantity_kg=Decimal("5"),
            price_usd=Decimal("150"),
            fee_usd=Decimal("10"),
        )
        expected_pnl = (Decimal("5") * Decimal("150")) - (Decimal("5") * Decimal("100")) - Decimal("10")
        assert change.realized_pnl_usd == Decimal(expected_pnl).quantize(Decimal("0.01"))

    def test_averaging_down_long(self, engine: PositionEngine):
        change = engine.apply_trade(
            current_net_kg=Decimal("10"),
            current_avg_price=Decimal("200"),
            current_realized_pnl=Decimal("0"),
            side="buy",
            quantity_kg=Decimal("10"),
            price_usd=Decimal("100"),
        )
        assert change.new_avg_price_usd == Decimal("150")


class TestCalculateUnrealizedPnl:
    def test_long_position_profit(self, engine: PositionEngine):
        pnl = engine.calculate_unrealized_pnl(
            net_kg=Decimal("10"),
            avg_price_usd=Decimal("100"),
            mark_price_usd=Decimal("150"),
        )
        assert pnl == Decimal("500")

    def test_long_position_loss(self, engine: PositionEngine):
        pnl = engine.calculate_unrealized_pnl(
            net_kg=Decimal("10"),
            avg_price_usd=Decimal("100"),
            mark_price_usd=Decimal("50"),
        )
        assert pnl == Decimal("-500")

    def test_short_position_profit(self, engine: PositionEngine):
        pnl = engine.calculate_unrealized_pnl(
            net_kg=Decimal("-10"),
            avg_price_usd=Decimal("100"),
            mark_price_usd=Decimal("50"),
        )
        assert pnl == Decimal("500")

    def test_short_position_loss(self, engine: PositionEngine):
        pnl = engine.calculate_unrealized_pnl(
            net_kg=Decimal("-10"),
            avg_price_usd=Decimal("100"),
            mark_price_usd=Decimal("150"),
        )
        assert pnl == Decimal("-500")

    def test_zero_position(self, engine: PositionEngine):
        pnl = engine.calculate_unrealized_pnl(
            net_kg=Decimal("0"),
            avg_price_usd=Decimal("100"),
            mark_price_usd=Decimal("150"),
        )
        assert pnl == Decimal("0")

    def test_small_quantities_precise(self, engine: PositionEngine):
        pnl = engine.calculate_unrealized_pnl(
            net_kg=Decimal("0.001"),
            avg_price_usd=Decimal("100.50"),
            mark_price_usd=Decimal("101.50"),
        )
        assert pnl == Decimal("0.00").quantize(Decimal("0.01"))


class TestCalculateLiquidationPrice:
    def test_long_position_liquidation_price(self, engine: PositionEngine):
        price = engine.calculate_liquidation_price(
            net_kg=Decimal("10"),
            avg_price_usd=Decimal("100"),
            margin_balance_usd=Decimal("500"),
            maintenance_margin_ratio=Decimal("0.5"),
        )
        assert price is not None
        assert price < Decimal("100")

    def test_short_position_liquidation_price(self, engine: PositionEngine):
        price = engine.calculate_liquidation_price(
            net_kg=Decimal("-10"),
            avg_price_usd=Decimal("100"),
            margin_balance_usd=Decimal("500"),
            maintenance_margin_ratio=Decimal("0.5"),
        )
        assert price is not None
        assert price > Decimal("100")

    def test_zero_position_returns_none(self, engine: PositionEngine):
        price = engine.calculate_liquidation_price(
            net_kg=Decimal("0"),
            avg_price_usd=Decimal("100"),
            margin_balance_usd=Decimal("500"),
            maintenance_margin_ratio=Decimal("0.5"),
        )
        assert price is None

    def test_liquidation_price_with_leverage(self, engine: PositionEngine):
        price = engine.calculate_liquidation_price(
            net_kg=Decimal("10"),
            avg_price_usd=Decimal("100"),
            margin_balance_usd=Decimal("200"),
            maintenance_margin_ratio=Decimal("0.5"),
            leverage=Decimal("5"),
        )
        assert price is not None

    def test_liquidation_price_minimum_floor(self, engine: PositionEngine):
        price = engine.calculate_liquidation_price(
            net_kg=Decimal("10"),
            avg_price_usd=Decimal("100"),
            margin_balance_usd=Decimal("10000"),
            maintenance_margin_ratio=Decimal("0.5"),
        )
        assert price is None or price > Decimal("0")


class TestPositionValue:
    def test_long_position_value(self, engine: PositionEngine):
        value = engine.position_value(
            net_kg=Decimal("10"),
            price_usd=Decimal("100"),
        )
        assert value == Decimal("1000")

    def test_short_position_value(self, engine: PositionEngine):
        value = engine.position_value(
            net_kg=Decimal("-10"),
            price_usd=Decimal("100"),
        )
        assert value == Decimal("1000")

    def test_zero_position(self, engine: PositionEngine):
        value = engine.position_value(
            net_kg=Decimal("0"),
            price_usd=Decimal("100"),
        )
        assert value == Decimal("0")

    def test_large_position(self, engine: PositionEngine):
        value = engine.position_value(
            net_kg=Decimal("1000"),
            price_usd=Decimal("999.99"),
        )
        assert value == Decimal("999990.00")


class TestCalculatePnlAtPrice:
    def test_long_profit(self, engine: PositionEngine):
        pnl = engine.calculate_pnl_at_price(
            net_kg=Decimal("10"),
            avg_price_usd=Decimal("100"),
            target_price_usd=Decimal("150"),
        )
        assert pnl == Decimal("500")

    def test_short_profit(self, engine: PositionEngine):
        pnl = engine.calculate_pnl_at_price(
            net_kg=Decimal("-10"),
            avg_price_usd=Decimal("100"),
            target_price_usd=Decimal("50"),
        )
        assert pnl == Decimal("500")

    def test_zero_net_kg(self, engine: PositionEngine):
        pnl = engine.calculate_pnl_at_price(
            net_kg=Decimal("0"),
            avg_price_usd=Decimal("100"),
            target_price_usd=Decimal("150"),
        )
        assert pnl == Decimal("0")
