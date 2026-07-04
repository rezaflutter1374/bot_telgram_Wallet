from __future__ import annotations

from decimal import Decimal

import pytest

from domain.enums import LiquidationStatus
from domain.services.liquidation_engine import (
    LiquidationEngine,
    LiquidationOrder,
    LiquidationPriority,
)


def _make_order(
    user_id: int = 1,
    net_kg: str = "10",
    avg_price: str = "100",
    margin_ratio: str = "0.8",
    equity: str = "2000",
    used_margin: str = "1000",
    leverage: str = "5",
    unrealized_pnl: str = "-500",
) -> LiquidationOrder:
    return LiquidationOrder(
        user_id=user_id,
        position_net_kg=Decimal(net_kg),
        position_avg_price_usd=Decimal(avg_price),
        margin_ratio=Decimal(margin_ratio),
        equity_usd=Decimal(equity),
        used_margin_usd=Decimal(used_margin),
        leverage=Decimal(leverage),
        unrealized_pnl_usd=Decimal(unrealized_pnl),
    )


@pytest.fixture
def engine() -> LiquidationEngine:
    return LiquidationEngine(insurance_fund_balance_usd=Decimal("10000"))


class TestPrioritize:
    def test_highest_leverage_strategy(self, engine: LiquidationEngine):
        orders = [
            _make_order(user_id=1, leverage="2"),
            _make_order(user_id=2, leverage="10"),
            _make_order(user_id=3, leverage="5"),
        ]
        result = engine.prioritize(orders, LiquidationPriority.highest_leverage_first)
        assert result[0].user_id == 2
        assert result[1].user_id == 3
        assert result[2].user_id == 1

    def test_largest_loss_strategy(self, engine: LiquidationEngine):
        orders = [
            _make_order(user_id=1, unrealized_pnl="-100"),
            _make_order(user_id=2, unrealized_pnl="-1000"),
            _make_order(user_id=3, unrealized_pnl="-500"),
        ]
        result = engine.prioritize(orders, LiquidationPriority.largest_loss_first)
        assert result[0].user_id == 2
        assert result[1].user_id == 3
        assert result[2].user_id == 1

    def test_lowest_margin_ratio_strategy(self, engine: LiquidationEngine):
        orders = [
            _make_order(user_id=1, margin_ratio="0.9"),
            _make_order(user_id=2, margin_ratio="0.3"),
            _make_order(user_id=3, margin_ratio="0.6"),
        ]
        result = engine.prioritize(orders, LiquidationPriority.lowest_margin_ratio)
        assert result[0].user_id == 2
        assert result[1].user_id == 3
        assert result[2].user_id == 1

    def test_oldest_first_strategy(self, engine: LiquidationEngine):
        orders = [
            _make_order(user_id=1),
            _make_order(user_id=2),
            _make_order(user_id=3),
        ]
        result = engine.prioritize(orders, LiquidationPriority.oldest_first)
        assert result == orders

    def test_default_strategy_is_lowest_margin_ratio(self, engine: LiquidationEngine):
        orders = [
            _make_order(user_id=1, margin_ratio="0.9"),
            _make_order(user_id=2, margin_ratio="0.3"),
        ]
        result = engine.prioritize(orders)
        assert result[0].user_id == 2

    def test_empty_list(self, engine: LiquidationEngine):
        result = engine.prioritize([])
        assert result == []

    def test_single_order(self, engine: LiquidationEngine):
        orders = [_make_order(user_id=1)]
        result = engine.prioritize(orders)
        assert len(result) == 1
        assert result[0].user_id == 1


class TestCalculateLiquidationPrice:
    def test_long_position(self, engine: LiquidationEngine):
        price = engine.calculate_liquidation_price(
            net_kg=Decimal("10"),
            avg_price_usd=Decimal("100"),
            maintenance_margin_usd=Decimal("500"),
            margin_balance_usd=Decimal("2000"),
            side="buy",
        )
        assert price is not None
        assert price < Decimal("100")

    def test_short_position(self, engine: LiquidationEngine):
        price = engine.calculate_liquidation_price(
            net_kg=Decimal("-10"),
            avg_price_usd=Decimal("100"),
            maintenance_margin_usd=Decimal("500"),
            margin_balance_usd=Decimal("2000"),
            side="sell",
        )
        assert price is not None
        assert price > Decimal("100")

    def test_zero_net_kg(self, engine: LiquidationEngine):
        price = engine.calculate_liquidation_price(
            net_kg=Decimal("0"),
            avg_price_usd=Decimal("100"),
            maintenance_margin_usd=Decimal("500"),
            margin_balance_usd=Decimal("2000"),
            side="buy",
        )
        assert price is None

    def test_liquidation_price_floor(self, engine: LiquidationEngine):
        price = engine.calculate_liquidation_price(
            net_kg=Decimal("10"),
            avg_price_usd=Decimal("100"),
            maintenance_margin_usd=Decimal("50"),
            margin_balance_usd=Decimal("10000"),
            side="buy",
        )
        assert price is None or price > Decimal("0")


class TestExecuteLiquidation:
    def test_full_liquidation_with_profit(self, engine: LiquidationEngine):
        order = _make_order(net_kg="10", avg_price="100", equity="2000", leverage="1")
        result = engine.execute_liquidation(order, mark_price_usd=Decimal("150"), max_close_ratio=Decimal("1"))
        assert result.status == LiquidationStatus.completed
        assert result.filled_quantity_kg == Decimal("10")
        assert result.loss_realized_usd == Decimal("0")
        assert result.is_partial is False
        assert result.remaining_quantity_kg == Decimal("0")

    def test_full_liquidation_with_loss(self, engine: LiquidationEngine):
        order = _make_order(net_kg="10", avg_price="100", equity="1000", leverage="1")
        result = engine.execute_liquidation(order, mark_price_usd=Decimal("50"), max_close_ratio=Decimal("1"))
        assert result.status == LiquidationStatus.completed
        assert result.loss_realized_usd == Decimal("500")
        assert result.is_partial is False

    def test_partial_liquidation(self, engine: LiquidationEngine):
        order = _make_order(net_kg="10", avg_price="100", equity="2000")
        result = engine.execute_liquidation(order, mark_price_usd=Decimal("50"), max_close_ratio=Decimal("0.5"))
        assert result.status == LiquidationStatus.partial
        assert result.filled_quantity_kg == Decimal("5")
        assert result.is_partial is True
        assert result.remaining_quantity_kg == Decimal("5")

    def test_insurance_fund_covers_shortfall(self, engine: LiquidationEngine):
        order = _make_order(net_kg="10", avg_price="100", equity="100", leverage="1")
        result = engine.execute_liquidation(order, mark_price_usd=Decimal("1"), max_close_ratio=Decimal("1"))
        expected_loss = (Decimal("100") - Decimal("1")) * Decimal("10")
        shortfall = expected_loss - Decimal("100")
        assert result.insurance_used_usd == min(shortfall, Decimal("10000"))
        assert result.status == LiquidationStatus.completed

    def test_insurance_fund_insufficient_partial_coverage(self, engine: LiquidationEngine):
        engine.update_insurance_balance(Decimal("100"))
        order = _make_order(net_kg="10", avg_price="100", equity="100", leverage="1")
        result = engine.execute_liquidation(order, mark_price_usd=Decimal("1"), max_close_ratio=Decimal("1"))
        expected_loss = (Decimal("100") - Decimal("1")) * Decimal("10")
        shortfall = expected_loss - Decimal("100")
        assert result.insurance_used_usd == min(shortfall, Decimal("100"))
        assert result.insurance_used_usd == Decimal("100")

    def test_zero_insurance_balance(self, engine: LiquidationEngine):
        engine.update_insurance_balance(Decimal("0"))
        order = _make_order(net_kg="10", avg_price="100", equity="100", leverage="1")
        result = engine.execute_liquidation(order, mark_price_usd=Decimal("1"), max_close_ratio=Decimal("1"))
        assert result.insurance_used_usd == Decimal("0")

    def test_liquidation_with_zero_pnl(self, engine: LiquidationEngine):
        order = _make_order(net_kg="10", avg_price="100", equity="2000", leverage="1")
        result = engine.execute_liquidation(order, mark_price_usd=Decimal("100"), max_close_ratio=Decimal("1"))
        assert result.loss_realized_usd == Decimal("0")
        assert result.insurance_used_usd == Decimal("0")

    def test_short_position_liquidation(self, engine: LiquidationEngine):
        order = _make_order(net_kg="-10", avg_price="100", equity="2000", leverage="1")
        result = engine.execute_liquidation(order, mark_price_usd=Decimal("150"), max_close_ratio=Decimal("1"))
        assert result.status == LiquidationStatus.completed
        expected_loss = (Decimal("150") - Decimal("100")) * Decimal("10")
        assert result.loss_realized_usd == expected_loss.quantize(Decimal("0.01"))

    def test_zero_close_quantity(self, engine: LiquidationEngine):
        order = _make_order(net_kg="10", avg_price="100", equity="2000")
        result = engine.execute_liquidation(order, mark_price_usd=Decimal("50"), max_close_ratio=Decimal("0"))
        assert result.status == LiquidationStatus.failed
        assert result.filled_quantity_kg == Decimal("0")

    def test_loss_without_insurance_need(self, engine: LiquidationEngine):
        order = _make_order(net_kg="10", avg_price="100", equity="10000", leverage="1")
        result = engine.execute_liquidation(order, mark_price_usd=Decimal("50"), max_close_ratio=Decimal("1"))
        assert result.loss_realized_usd == Decimal("500")
        assert result.insurance_used_usd == Decimal("0")


class TestCheckLiquidationTrigger:
    def test_margin_ratio_below_threshold_triggers(self, engine: LiquidationEngine):
        triggered = engine.check_liquidation_trigger(
            margin_ratio=Decimal("0.3"),
            maintenance_threshold=Decimal("0.5"),
        )
        assert triggered is True

    def test_margin_ratio_above_threshold_does_not_trigger(self, engine: LiquidationEngine):
        triggered = engine.check_liquidation_trigger(
            margin_ratio=Decimal("0.6"),
            maintenance_threshold=Decimal("0.5"),
        )
        assert triggered is False

    def test_at_threshold_boundary(self, engine: LiquidationEngine):
        triggered = engine.check_liquidation_trigger(
            margin_ratio=Decimal("0.5"),
            maintenance_threshold=Decimal("0.5"),
        )
        assert triggered is False

    def test_custom_threshold(self, engine: LiquidationEngine):
        triggered = engine.check_liquidation_trigger(
            margin_ratio=Decimal("0.7"),
            maintenance_threshold=Decimal("0.8"),
        )
        assert triggered is True

    def test_zero_margin_ratio(self, engine: LiquidationEngine):
        triggered = engine.check_liquidation_trigger(
            margin_ratio=Decimal("0"),
            maintenance_threshold=Decimal("0.5"),
        )
        assert triggered is True


class TestUpdateInsuranceBalance:
    def test_balance_updates_correctly(self, engine: LiquidationEngine):
        engine.update_insurance_balance(Decimal("50000"))
        order = _make_order(net_kg="10", avg_price="100", equity="100", leverage="1")
        engine.execute_liquidation(order, mark_price_usd=Decimal("1"), max_close_ratio=Decimal("1"))
        new_balance = engine._insurance_balance
        assert new_balance < Decimal("50000")

    def test_initial_balance(self, engine: LiquidationEngine):
        assert engine._insurance_balance == Decimal("10000")

    def test_zero_balance_set(self, engine: LiquidationEngine):
        engine.update_insurance_balance(Decimal("0"))
        assert engine._insurance_balance == Decimal("0")

    def test_large_balance(self, engine: LiquidationEngine):
        engine.update_insurance_balance(Decimal("999999.99"))
        assert engine._insurance_balance == Decimal("999999.99")


class TestLiquidationResult:
    def test_result_contains_details(self, engine: LiquidationEngine):
        order = _make_order(net_kg="10", avg_price="100", equity="2000")
        result = engine.execute_liquidation(order, mark_price_usd=Decimal("50"), max_close_ratio=Decimal("1"))
        assert "mark_price_usd" in result.details
        assert "close_ratio" in result.details

    def test_partial_liquidation_status(self, engine: LiquidationEngine):
        order = _make_order(net_kg="10", avg_price="100", equity="2000")
        result = engine.execute_liquidation(order, mark_price_usd=Decimal("50"), max_close_ratio=Decimal("0.3"))
        assert result.status == LiquidationStatus.partial

    def test_full_liquidation_status(self, engine: LiquidationEngine):
        order = _make_order(net_kg="10", avg_price="100", equity="2000")
        result = engine.execute_liquidation(order, mark_price_usd=Decimal("50"), max_close_ratio=Decimal("1"))
        assert result.status == LiquidationStatus.completed
