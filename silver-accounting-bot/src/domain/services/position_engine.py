from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PositionState:
    user_id: int
    net_kg: Decimal
    avg_price_usd: Decimal
    realized_pnl_usd: Decimal
    unrealized_pnl_usd: Decimal
    total_fees_paid_usd: Decimal
    total_funding_paid_usd: Decimal
    trade_count: int
    last_settlement_price_usd: Decimal


@dataclass(frozen=True)
class PositionChange:
    delta_kg: Decimal
    price_usd: Decimal
    fee_usd: Decimal
    is_buy: bool
    is_reduce: bool
    new_net_kg: Decimal
    new_avg_price_usd: Decimal
    realized_pnl_usd: Decimal


class PositionEngine:
    def apply_trade(
        self,
        current_net_kg: Decimal,
        current_avg_price: Decimal,
        current_realized_pnl: Decimal,
        side: str,
        quantity_kg: Decimal,
        price_usd: Decimal,
        fee_usd: Decimal = Decimal("0"),
    ) -> PositionChange:
        is_buy = side == "buy"
        delta_kg = quantity_kg if is_buy else -quantity_kg
        new_net = current_net_kg + delta_kg
        realized_pnl = Decimal("0")

        if (current_net_kg > 0 and not is_buy) or (current_net_kg < 0 and is_buy):
            is_reduce = True
            reduce_qty = min(quantity_kg, abs(current_net_kg))
            if reduce_qty > 0:
                entry_value = reduce_qty * current_avg_price
                exit_value = reduce_qty * price_usd
                if current_net_kg > 0:
                    realized_pnl = exit_value - entry_value
                else:
                    realized_pnl = entry_value - exit_value
                realized_pnl = (realized_pnl - fee_usd).quantize(Decimal("0.01"))
        else:
            is_reduce = False

        new_avg_price = current_avg_price
        if not is_reduce and new_net != 0:
            old_value = abs(current_net_kg) * current_avg_price
            new_value = quantity_kg * price_usd
            total_qty = abs(new_net)
            new_avg_price = ((old_value + new_value) / total_qty).quantize(Decimal("0.000001"))

        return PositionChange(
            delta_kg=delta_kg,
            price_usd=price_usd,
            fee_usd=fee_usd,
            is_buy=is_buy,
            is_reduce=is_reduce,
            new_net_kg=new_net.quantize(Decimal("0.000001")),
            new_avg_price_usd=new_avg_price,
            realized_pnl_usd=realized_pnl.quantize(Decimal("0.01")),
        )

    def calculate_unrealized_pnl(
        self,
        net_kg: Decimal,
        avg_price_usd: Decimal,
        mark_price_usd: Decimal,
    ) -> Decimal:
        if net_kg == 0:
            return Decimal("0")
        if net_kg > 0:
            return ((mark_price_usd - avg_price_usd) * net_kg).quantize(Decimal("0.01"))
        return ((avg_price_usd - mark_price_usd) * abs(net_kg)).quantize(Decimal("0.01"))

    def calculate_liquidation_price(
        self,
        net_kg: Decimal,
        avg_price_usd: Decimal,
        margin_balance_usd: Decimal,
        maintenance_margin_ratio: Decimal,
        leverage: Decimal = Decimal("1"),
    ) -> Decimal | None:
        if net_kg == 0:
            return None
        abs_kg = abs(net_kg)
        if abs_kg == 0:
            return None
        if net_kg > 0:
            liq_price = avg_price_usd - (margin_balance_usd / abs_kg) * (Decimal("1") - maintenance_margin_ratio)
        else:
            liq_price = avg_price_usd + (margin_balance_usd / abs_kg) * (Decimal("1") - maintenance_margin_ratio)
        if liq_price <= 0:
            return Decimal("0.000001")
        return liq_price.quantize(Decimal("0.000001"))

    def calculate_pnl_at_price(
        self,
        net_kg: Decimal,
        avg_price_usd: Decimal,
        target_price_usd: Decimal,
    ) -> Decimal:
        if net_kg == 0:
            return Decimal("0")
        if net_kg > 0:
            return ((target_price_usd - avg_price_usd) * net_kg).quantize(Decimal("0.01"))
        return ((avg_price_usd - target_price_usd) * abs(net_kg)).quantize(Decimal("0.01"))

    def position_value(self, net_kg: Decimal, price_usd: Decimal) -> Decimal:
        return (abs(net_kg) * price_usd).quantize(Decimal("0.01"))
