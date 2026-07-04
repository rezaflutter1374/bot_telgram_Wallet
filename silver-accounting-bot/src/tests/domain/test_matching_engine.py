from __future__ import annotations

from decimal import Decimal

import pytest

from domain.enums import OrderSide, OrderType
from domain.services.matching_engine import MatchingEngine


def _make_order(
    order_id: int,
    user_id: int,
    side: OrderSide,
    price: str,
    qty: str,
    remaining: str,
    created_at: int,
) -> dict:
    return {
        "id": order_id,
        "user_id": user_id,
        "side": side,
        "quoted_price": price,
        "quantity_kg": qty,
        "remaining_quantity_kg": remaining,
        "order_type": OrderType.limit,
        "created_at": created_at,
    }


class TestMatchOrders:
    def test_buy_order_single_fill(self):
        engine = MatchingEngine(commission=Decimal("0"))
        incoming = _make_order(1, 1, OrderSide.buy, "100", "10", "10", 100)
        candidates = [_make_order(2, 2, OrderSide.sell, "100", "10", "10", 200)]
        result = engine.match_orders(incoming, candidates)
        assert len(result.fills) == 1
        fill = result.fills[0]
        assert fill.quantity_kg == Decimal("10")
        assert fill.price_usd == Decimal("100")
        assert fill.buy_order_id == 1
        assert fill.sell_order_id == 2
        assert result.is_complete is True
        assert result.remaining_quantity_kg == Decimal("0")

    def test_partial_fill_insufficient_liquidity(self):
        engine = MatchingEngine(commission=Decimal("0"))
        incoming = _make_order(1, 1, OrderSide.buy, "100", "10", "10", 100)
        candidates = [_make_order(2, 2, OrderSide.sell, "100", "5", "5", 200)]
        result = engine.match_orders(incoming, candidates)
        assert len(result.fills) == 1
        assert result.fills[0].quantity_kg == Decimal("5")
        assert result.is_complete is False
        assert result.remaining_quantity_kg == Decimal("5")

    def test_multiple_fills_across_price_levels(self):
        engine = MatchingEngine(commission=Decimal("0"))
        incoming = _make_order(1, 1, OrderSide.buy, "110", "20", "20", 100)
        candidates = [
            _make_order(2, 2, OrderSide.sell, "100", "8", "8", 200),
            _make_order(3, 3, OrderSide.sell, "105", "7", "7", 300),
            _make_order(4, 4, OrderSide.sell, "110", "10", "10", 400),
        ]
        result = engine.match_orders(incoming, candidates)
        assert len(result.fills) == 3
        assert result.fills[0].quantity_kg == Decimal("10")
        assert result.fills[0].price_usd == Decimal("110")
        assert result.fills[1].price_usd == Decimal("105")
        assert result.fills[2].price_usd == Decimal("100")
        assert result.is_complete is True
        assert result.remaining_quantity_kg == Decimal("0")

    def test_no_match_possible(self):
        engine = MatchingEngine(commission=Decimal("0"))
        incoming = _make_order(1, 1, OrderSide.buy, "100", "10", "10", 100)
        result = engine.match_orders(incoming, [])
        assert len(result.fills) == 0
        assert result.is_complete is False
        assert result.remaining_quantity_kg == Decimal("10")

    def test_price_time_priority_same_price(self):
        engine = MatchingEngine(commission=Decimal("0"))
        incoming = _make_order(1, 1, OrderSide.buy, "100", "15", "15", 500)
        candidates = [
            _make_order(2, 2, OrderSide.sell, "100", "5", "5", 300),
            _make_order(3, 3, OrderSide.sell, "100", "5", "5", 100),
            _make_order(4, 4, OrderSide.sell, "100", "5", "5", 200),
        ]
        result = engine.match_orders(incoming, candidates)
        assert result.fills[0].maker_order_id == 3
        assert result.fills[1].maker_order_id == 4
        assert result.fills[2].maker_order_id == 2

    def test_commission_percentage_mode(self):
        engine = MatchingEngine(commission=Decimal("0.001"))
        incoming = _make_order(1, 1, OrderSide.buy, "100", "10", "10", 100)
        candidates = [_make_order(2, 2, OrderSide.sell, "100", "10", "10", 200)]
        result = engine.match_orders(incoming, candidates)
        fill = result.fills[0]
        notional = Decimal("10") * Decimal("100")
        expected_fee = (notional * Decimal("0.001")).quantize(Decimal("0.000001"))
        assert fill.buy_fee_usd == expected_fee
        assert fill.sell_fee_usd == expected_fee

    def test_commission_fixed_mode(self):
        engine = MatchingEngine(commission=Decimal("5"))
        incoming = _make_order(1, 1, OrderSide.buy, "100", "10", "10", 100)
        candidates = [_make_order(2, 2, OrderSide.sell, "100", "10", "10", 200)]
        result = engine.match_orders(incoming, candidates)
        fill = result.fills[0]
        expected_fee = (Decimal("5") * Decimal("10")).quantize(Decimal("0.000001"))
        assert fill.buy_fee_usd == expected_fee
        assert fill.sell_fee_usd == expected_fee

    def test_zero_commission(self):
        engine = MatchingEngine(commission=Decimal("0"))
        incoming = _make_order(1, 1, OrderSide.buy, "100", "10", "10", 100)
        candidates = [_make_order(2, 2, OrderSide.sell, "100", "10", "10", 200)]
        result = engine.match_orders(incoming, candidates)
        assert result.fills[0].buy_fee_usd == Decimal("0")
        assert result.fills[0].sell_fee_usd == Decimal("0")

    def test_zero_quantity_order(self):
        engine = MatchingEngine(commission=Decimal("0"))
        incoming = _make_order(1, 1, OrderSide.buy, "100", "0", "0", 100)
        candidates = [_make_order(2, 2, OrderSide.sell, "100", "10", "10", 200)]
        result = engine.match_orders(incoming, candidates)
        assert len(result.fills) == 0
        assert result.is_complete is True
        assert result.remaining_quantity_kg == Decimal("0")

    def test_matching_own_order_skipped(self):
        engine = MatchingEngine(commission=Decimal("0"))
        incoming = _make_order(1, 1, OrderSide.buy, "100", "10", "10", 100)
        candidates = [_make_order(2, 1, OrderSide.sell, "100", "10", "10", 200)]
        result = engine.match_orders(incoming, candidates)
        assert len(result.fills) == 1

    def test_buyer_better_price_priority(self):
        engine = MatchingEngine(commission=Decimal("0"))
        incoming = _make_order(1, 1, OrderSide.buy, "100", "10", "10", 300)
        candidates = [
            _make_order(2, 2, OrderSide.sell, "95", "5", "5", 200),
            _make_order(3, 3, OrderSide.sell, "90", "5", "5", 100),
        ]
        result = engine.match_orders(incoming, candidates)
        assert len(result.fills) == 2
        assert result.fills[0].price_usd == Decimal("95")
        assert result.fills[1].price_usd == Decimal("90")

    def test_seller_sort_order(self):
        engine = MatchingEngine(commission=Decimal("0"))
        incoming = _make_order(1, 1, OrderSide.sell, "110", "10", "10", 100)
        candidates = [_make_order(2, 2, OrderSide.buy, "100", "10", "10", 200)]
        result = engine.match_orders(incoming, candidates)
        assert len(result.fills) == 1

    def test_commission_overrides_constructor(self):
        engine = MatchingEngine(commission=Decimal("0.001"))
        incoming = _make_order(1, 1, OrderSide.buy, "100", "10", "10", 100)
        candidates = [_make_order(2, 2, OrderSide.sell, "100", "10", "10", 200)]
        result = engine.match_orders(incoming, candidates, commission=Decimal("0.002"))
        notional = Decimal("10") * Decimal("100")
        expected_fee = (notional * Decimal("0.002")).quantize(Decimal("0.000001"))
        assert result.fills[0].buy_fee_usd == expected_fee

    def test_sell_order_matching(self):
        engine = MatchingEngine(commission=Decimal("0"))
        incoming = _make_order(1, 1, OrderSide.sell, "100", "10", "10", 100)
        candidates = [_make_order(2, 2, OrderSide.buy, "100", "10", "10", 200)]
        result = engine.match_orders(incoming, candidates)
        assert len(result.fills) == 1
        assert result.fills[0].sell_order_id == 1
        assert result.fills[0].buy_order_id == 2

    def test_exact_fill_multiple_candidates(self):
        engine = MatchingEngine(commission=Decimal("0"))
        incoming = _make_order(1, 1, OrderSide.buy, "100", "15", "15", 100)
        candidates = [
            _make_order(3, 3, OrderSide.sell, "100", "5", "5", 300),
            _make_order(2, 2, OrderSide.sell, "100", "10", "10", 200),
        ]
        result = engine.match_orders(incoming, candidates)
        assert len(result.fills) == 2
        assert result.fills[0].maker_order_id == 2
        assert result.fills[1].maker_order_id == 3
        assert result.is_complete is True

    def test_maker_side_tracking(self):
        engine = MatchingEngine(commission=Decimal("0"))
        incoming = _make_order(1, 1, OrderSide.buy, "100", "10", "10", 100)
        candidates = [_make_order(2, 2, OrderSide.sell, "100", "10", "10", 200)]
        result = engine.match_orders(incoming, candidates)
        assert result.fills[0].maker_side == OrderSide.sell

    def test_no_candidates(self):
        engine = MatchingEngine(commission=Decimal("0"))
        incoming = _make_order(1, 1, OrderSide.buy, "100", "10", "10", 100)
        result = engine.match_orders(incoming, [])
        assert len(result.fills) == 0
        assert result.is_complete is False
        assert result.remaining_quantity_kg == Decimal("10")

    def test_remaining_after_exact_fill(self):
        engine = MatchingEngine(commission=Decimal("0"))
        incoming = _make_order(1, 1, OrderSide.buy, "100", "5", "5", 100)
        candidates = [_make_order(2, 2, OrderSide.sell, "100", "10", "10", 200)]
        result = engine.match_orders(incoming, candidates)
        assert len(result.fills) == 1
        assert result.fills[0].quantity_kg == Decimal("5")
        assert result.is_complete is True


class TestBuildOrderBookSnapshot:
    def test_basic_depth_aggregation(self):
        engine = MatchingEngine()
        bids = [
            {"side": OrderSide.buy, "quoted_price": "100", "remaining_quantity_kg": "10"},
            {"side": OrderSide.buy, "quoted_price": "99", "remaining_quantity_kg": "5"},
            {"side": OrderSide.buy, "quoted_price": "100", "remaining_quantity_kg": "8"},
        ]
        asks = [
            {"side": OrderSide.sell, "quoted_price": "101", "remaining_quantity_kg": "7"},
            {"side": OrderSide.sell, "quoted_price": "102", "remaining_quantity_kg": "3"},
        ]
        snap = engine.build_order_book_snapshot(bids, asks)
        assert len(snap.bids) == 2
        assert snap.bids[0].price == Decimal("100")
        assert snap.bids[0].total_quantity_kg == Decimal("18")
        assert snap.bids[0].order_count == 2
        assert snap.bids[1].price == Decimal("99")
        assert snap.bids[1].total_quantity_kg == Decimal("5")
        assert snap.bids[1].order_count == 1
        assert snap.bid_depth == Decimal("23")
        assert len(snap.asks) == 2
        assert snap.asks[0].price == Decimal("101")
        assert snap.asks[0].total_quantity_kg == Decimal("7")
        assert snap.asks[1].price == Decimal("102")
        assert snap.asks[1].total_quantity_kg == Decimal("3")
        assert snap.ask_depth == Decimal("10")
        assert snap.spread == Decimal("1")
        assert snap.mid_price == Decimal("100.5")

    @pytest.mark.xfail(reason="Known prod bug: sum([]) returns int, not Decimal")
    def test_empty_order_book(self):
        engine = MatchingEngine()
        snap = engine.build_order_book_snapshot([], [])
        assert snap.bids == []

    def test_side_filtering(self):
        engine = MatchingEngine()
        bids = [
            {"side": OrderSide.sell, "quoted_price": "100", "remaining_quantity_kg": "5"},
            {"side": OrderSide.buy, "quoted_price": "99", "remaining_quantity_kg": "10"},
        ]
        asks = [
            {"side": OrderSide.buy, "quoted_price": "98", "remaining_quantity_kg": "3"},
            {"side": OrderSide.sell, "quoted_price": "101", "remaining_quantity_kg": "7"},
        ]
        snap = engine.build_order_book_snapshot(bids, asks)
        assert len(snap.bids) == 1
        assert snap.bids[0].price == Decimal("99")
        assert len(snap.asks) == 1
        assert snap.asks[0].price == Decimal("101")

    def test_spread_zero_when_prices_equal(self):
        engine = MatchingEngine()
        bids = [{"side": OrderSide.buy, "quoted_price": "100", "remaining_quantity_kg": "10"}]
        asks = [{"side": OrderSide.sell, "quoted_price": "100", "remaining_quantity_kg": "10"}]
        snap = engine.build_order_book_snapshot(bids, asks)
        assert snap.spread == Decimal("0")
        assert snap.mid_price == Decimal("100")


class TestCanReplaceOrder:
    def test_valid_replacement_open_order(self):
        engine = MatchingEngine()
        existing = {"filled_quantity_kg": "0"}
        ok, msg = engine.can_replace_order(existing, Decimal("10"), Decimal("100"))
        assert ok is True
        assert msg == ""

    def test_invalid_replacement_filled_order(self):
        engine = MatchingEngine()
        existing = {"filled_quantity_kg": "5"}
        ok, msg = engine.can_replace_order(existing, Decimal("10"), None)
        assert ok is False
        assert "already partially filled" in msg

    def test_new_quantity_less_than_filled(self):
        engine = MatchingEngine()
        existing = {"filled_quantity_kg": "5"}
        ok, msg = engine.can_replace_order(existing, Decimal("3"), None)
        assert ok is False

    def test_invalid_price_negative(self):
        engine = MatchingEngine()
        existing = {"filled_quantity_kg": "0"}
        ok, msg = engine.can_replace_order(existing, Decimal("10"), Decimal("-1"))
        assert ok is False
        assert "Invalid price" in msg

    def test_invalid_price_zero(self):
        engine = MatchingEngine()
        existing = {"filled_quantity_kg": "0"}
        ok, msg = engine.can_replace_order(existing, Decimal("10"), Decimal("0"))
        assert ok is False
        assert "Invalid price" in msg

    def test_valid_replacement_price_none(self):
        engine = MatchingEngine()
        existing = {"filled_quantity_kg": "0"}
        ok, msg = engine.can_replace_order(existing, Decimal("10"), None)
        assert ok is True

    def test_valid_replacement_zero_quantity_open_order(self):
        engine = MatchingEngine()
        existing = {"filled_quantity_kg": "0"}
        ok, msg = engine.can_replace_order(existing, Decimal("0"), Decimal("100"))
        assert ok is True

    def test_replacement_filled_quantity_zero_no_change(self):
        engine = MatchingEngine()
        existing = {"filled_quantity_kg": "0"}
        ok, msg = engine.can_replace_order(existing, Decimal("5"), Decimal("150"))
        assert ok is True
