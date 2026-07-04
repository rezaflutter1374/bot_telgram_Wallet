from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
from enum import Enum

from domain.enums import LiquidationStatus


class LiquidationPriority(str, Enum):
    highest_leverage_first = "highest_leverage_first"
    largest_loss_first = "largest_loss_first"
    lowest_margin_ratio = "lowest_margin_ratio"
    oldest_first = "oldest_first"


@dataclass(frozen=True)
class LiquidationOrder:
    user_id: int
    position_net_kg: Decimal
    position_avg_price_usd: Decimal
    margin_ratio: Decimal
    equity_usd: Decimal
    used_margin_usd: Decimal
    leverage: Decimal
    unrealized_pnl_usd: Decimal


@dataclass(frozen=True)
class LiquidationResult:
    user_id: int
    status: LiquidationStatus
    filled_quantity_kg: Decimal
    average_fill_price_usd: Decimal | None
    loss_realized_usd: Decimal
    insurance_used_usd: Decimal
    remaining_quantity_kg: Decimal
    is_partial: bool
    details: dict = field(default_factory=dict)


class LiquidationEngine:
    def __init__(self, insurance_fund_balance_usd: Decimal = Decimal("0")):
        self._insurance_balance = insurance_fund_balance_usd

    def update_insurance_balance(self, balance: Decimal) -> None:
        self._insurance_balance = balance

    def prioritize(
        self,
        candidates: list[LiquidationOrder],
        strategy: LiquidationPriority = LiquidationPriority.lowest_margin_ratio,
    ) -> list[LiquidationOrder]:
        if strategy == LiquidationPriority.highest_leverage_first:
            return sorted(candidates, key=lambda o: -o.leverage)
        elif strategy == LiquidationPriority.largest_loss_first:
            return sorted(candidates, key=lambda o: o.unrealized_pnl_usd)
        elif strategy == LiquidationPriority.oldest_first:
            return candidates
        return sorted(candidates, key=lambda o: o.margin_ratio)

    def calculate_liquidation_price(
        self,
        net_kg: Decimal,
        avg_price_usd: Decimal,
        maintenance_margin_usd: Decimal,
        margin_balance_usd: Decimal,
        side: str,  # "buy" or "sell" for the position
    ) -> Decimal | None:
        if net_kg == 0 or abs(net_kg) == 0:
            return None
        abs_kg = abs(net_kg)
        if net_kg > 0:
            liq_price = avg_price_usd - (margin_balance_usd - maintenance_margin_usd) / abs_kg
        else:
            liq_price = avg_price_usd + (margin_balance_usd - maintenance_margin_usd) / abs_kg
        if liq_price <= 0:
            return Decimal("0.000001")
        return liq_price.quantize(Decimal("0.000001"))

    def execute_liquidation(
        self,
        order: LiquidationOrder,
        mark_price_usd: Decimal,
        max_close_ratio: Decimal = Decimal("1"),  # 1 = full, 0.5 = half
    ) -> LiquidationResult:
        close_qty = (abs(order.position_net_kg) * max_close_ratio).quantize(Decimal("0.000001"))
        is_partial = close_qty < abs(order.position_net_kg)
        if close_qty <= 0:
            return LiquidationResult(
                user_id=order.user_id,
                status=LiquidationStatus.failed,
                filled_quantity_kg=Decimal("0"),
                average_fill_price_usd=None,
                loss_realized_usd=Decimal("0"),
                insurance_used_usd=Decimal("0"),
                remaining_quantity_kg=abs(order.position_net_kg),
                is_partial=False,
                details={"reason": "zero_close_quantity"},
            )

        if order.position_net_kg > 0:
            loss = (order.position_avg_price_usd - mark_price_usd) * close_qty
        else:
            loss = (mark_price_usd - order.position_avg_price_usd) * close_qty
        loss = max(loss, Decimal("0"))

        insurance_used = Decimal("0")
        if loss > order.equity_usd:
            shortfall = loss - order.equity_usd
            insurance_used = min(shortfall, self._insurance_balance)
            self._insurance_balance -= insurance_used

        return LiquidationResult(
            user_id=order.user_id,
            status=LiquidationStatus.completed if not is_partial else LiquidationStatus.partial,
            filled_quantity_kg=close_qty,
            average_fill_price_usd=mark_price_usd,
            loss_realized_usd=loss.quantize(Decimal("0.01")),
            insurance_used_usd=insurance_used.quantize(Decimal("0.01")),
            remaining_quantity_kg=abs(order.position_net_kg) - close_qty,
            is_partial=is_partial,
            details={
                "mark_price_usd": str(mark_price_usd),
                "close_ratio": str(max_close_ratio),
            },
        )

    def check_liquidation_trigger(
        self,
        margin_ratio: Decimal,
        maintenance_threshold: Decimal = Decimal("0.5"),
    ) -> bool:
        return margin_ratio < maintenance_threshold
