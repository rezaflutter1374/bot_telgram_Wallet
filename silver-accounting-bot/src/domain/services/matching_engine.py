from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from domain.enums import OrderSide, OrderType, OrderTimeInForce


class OrderBookSide(Enum):
    bids = "bids"
    asks = "asks"


@dataclass(frozen=True)
class PriceLevel:
    price: Decimal
    total_quantity_kg: Decimal
    order_count: int


@dataclass
class OrderBookEntry:
    order_id: int
    user_id: int
    side: OrderSide
    price: Decimal
    quantity_kg: Decimal
    remaining_quantity_kg: Decimal
    order_type: OrderType
    time_in_force: OrderTimeInForce
    post_only: bool
    reduce_only: bool
    created_at: int  # unix timestamp microsecond precision
    is_triggered: bool = True


@dataclass
class OrderBookSnapshot:
    bids: list[PriceLevel] = field(default_factory=list)
    asks: list[PriceLevel] = field(default_factory=list)
    bid_depth: Decimal = Decimal("0")
    ask_depth: Decimal = Decimal("0")
    spread: Decimal = Decimal("0")
    mid_price: Decimal | None = None


@dataclass(frozen=True)
class Fill:
    trade_id: int | None
    maker_order_id: int
    taker_order_id: int
    buy_order_id: int
    sell_order_id: int
    price_usd: Decimal
    quantity_kg: Decimal
    buy_fee_usd: Decimal
    sell_fee_usd: Decimal
    maker_side: OrderSide


@dataclass(frozen=True)
class MatchResult:
    fills: list[Fill] = field(default_factory=list)
    remaining_quantity_kg: Decimal = Decimal("0")
    is_complete: bool = False


class MatchingEngine:
    def __init__(self, commission: Decimal = Decimal("0")):
        self._commission = commission

    def set_commission(self, commission: Decimal) -> None:
        self._commission = commission

    def calculate_fee(self, notional_usd: Decimal, quantity_kg: Decimal) -> Decimal:
        if self._commission <= Decimal("0"):
            return Decimal("0")
        if self._commission <= Decimal("1"):
            return (notional_usd * self._commission).quantize(Decimal("0.000001"))
        return (self._commission * quantity_kg).quantize(Decimal("0.000001"))

    def price_crosses(self, incoming: dict, resting: dict) -> bool:
        if incoming["side"] == OrderSide.buy:
            if incoming["order_type"] == OrderType.market:
                return True
            return Decimal(resting["quoted_price"]) <= Decimal(incoming.get("limit_price", incoming["quoted_price"]))
        if incoming["order_type"] == OrderType.market:
            return True
        return Decimal(resting["quoted_price"]) >= Decimal(incoming.get("limit_price", incoming["quoted_price"]))

    def match_orders(
        self,
        incoming: dict,
        candidates: list[dict],
        commission: Decimal | None = None,
    ) -> MatchResult:
        """
        Price-time priority matching: candidates sorted by price (best first),
        then by created_at ascending (older first).
        """
        if commission is not None:
            self._commission = commission

        incoming_side = incoming["side"]
        incoming_qty = Decimal(incoming["remaining_quantity_kg"])
        quoted_price = Decimal(incoming["quoted_price"])

        buy_side = incoming_side == OrderSide.buy
        sorted_candidates = sorted(
            candidates,
            key=lambda r: (
                -Decimal(r["quoted_price"]) if buy_side else Decimal(r["quoted_price"]),
                r["created_at"],
            ),
        )

        fills: list[Fill] = []
        for resting in sorted_candidates:
            if incoming_qty <= 0:
                break
            fill_qty = min(incoming_qty, Decimal(resting["remaining_quantity_kg"]))
            if fill_qty <= 0:
                continue
            trade_price = Decimal(resting["quoted_price"])
            trade_notional = (fill_qty * trade_price).quantize(Decimal("0.000001"))
            buy_fee = self.calculate_fee(notional_usd=trade_notional, quantity_kg=fill_qty)
            sell_fee = self.calculate_fee(notional_usd=trade_notional, quantity_kg=fill_qty)
            buy_order_id = incoming["id"] if incoming_side == OrderSide.buy else resting["id"]
            sell_order_id = incoming["id"] if incoming_side == OrderSide.sell else resting["id"]
            fills.append(Fill(
                trade_id=None,
                maker_order_id=resting["id"],
                taker_order_id=incoming["id"],
                buy_order_id=buy_order_id,
                sell_order_id=sell_order_id,
                price_usd=trade_price,
                quantity_kg=fill_qty,
                buy_fee_usd=buy_fee,
                sell_fee_usd=sell_fee,
                maker_side=resting["side"],
            ))
            incoming_qty -= fill_qty

        return MatchResult(
            fills=fills,
            remaining_quantity_kg=incoming_qty,
            is_complete=incoming_qty <= 0,
        )

    def build_order_book_snapshot(self, bids: list[dict], asks: list[dict]) -> OrderBookSnapshot:
        def _aggregate(entries: list[dict], side: OrderSide) -> list[PriceLevel]:
            levels: dict[Decimal, dict] = {}
            for e in entries:
                if e.get("side") != side:
                    continue
                p = Decimal(e["quoted_price"])
                if p not in levels:
                    levels[p] = {"price": p, "total_quantity_kg": Decimal("0"), "order_count": 0}
                levels[p]["total_quantity_kg"] += Decimal(e["remaining_quantity_kg"])
                levels[p]["order_count"] += 1
            sorted_levels = sorted(levels.values(), key=lambda x: -x["price"] if side == OrderSide.buy else x["price"])
            return [PriceLevel(**l) for l in sorted_levels]

        bid_levels = _aggregate(bids, OrderSide.buy)
        ask_levels = _aggregate(asks, OrderSide.sell)
        bid_depth = sum(l.total_quantity_kg for l in bid_levels)
        ask_depth = sum(l.total_quantity_kg for l in ask_levels)
        spread = Decimal("0")
        mid_price: Decimal | None = None
        if bid_levels and ask_levels:
            best_bid = bid_levels[0].price
            best_ask = ask_levels[0].price
            spread = (best_ask - best_bid).quantize(Decimal("0.000001"))
            mid_price = ((best_bid + best_ask) / Decimal("2")).quantize(Decimal("0.000001"))
        return OrderBookSnapshot(
            bids=bid_levels,
            asks=ask_levels,
            bid_depth=bid_depth.quantize(Decimal("0.000001")),
            ask_depth=ask_depth.quantize(Decimal("0.000001")),
            spread=spread,
            mid_price=mid_price,
        )

    def can_replace_order(self, existing: dict, new_quantity_kg: Decimal, new_price: Decimal | None) -> tuple[bool, str]:
        if Decimal(existing.get("filled_quantity_kg", 0)) > 0:
            return False, "Order already partially filled"
        if new_quantity_kg < Decimal(existing.get("filled_quantity_kg", 0)):
            return False, "New quantity less than filled quantity"
        if new_price is not None and new_price <= 0:
            return False, "Invalid price"
        return True, ""
