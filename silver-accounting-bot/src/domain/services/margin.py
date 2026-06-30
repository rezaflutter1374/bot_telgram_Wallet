from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from domain.enums import MarginAlertLevel, MarginMode


@dataclass(frozen=True)
class MarginSnapshot:
    margin_mode: MarginMode
    exposure_kg: Decimal
    available_balance_usd: Decimal
    frozen_balance_usd: Decimal
    margin_balance_usd: Decimal
    equity_usd: Decimal
    initial_margin_usd: Decimal
    maintenance_margin_usd: Decimal
    used_margin_usd: Decimal
    free_margin_usd: Decimal
    available_margin_usd: Decimal
    margin_utilization: Decimal
    margin_ratio: Decimal
    leverage: Decimal
    liquidation_price_usd: Decimal | None
    health: MarginAlertLevel
    floating_pnl_usd: Decimal
    realized_pnl_usd: Decimal
    unrealized_pnl_usd: Decimal


class MarginCalculator:
    def __init__(
        self,
        deposit_requirement_per_kg_usd: Decimal,
        maintenance_ratio_threshold: Decimal,
        *,
        warning_ratio_threshold: Decimal = Decimal("1.25"),
        liquidation_ratio_threshold: Decimal = Decimal("0.50"),
        default_max_leverage: Decimal = Decimal("5"),
    ) -> None:
        self._deposit_requirement_per_kg_usd = deposit_requirement_per_kg_usd
        self._maintenance_ratio_threshold = maintenance_ratio_threshold
        self._warning_ratio_threshold = warning_ratio_threshold
        self._liquidation_ratio_threshold = liquidation_ratio_threshold
        self._default_max_leverage = default_max_leverage

    def required_deposit_usd(self, exposure_kg: Decimal) -> Decimal:
        if exposure_kg <= 0:
            return Decimal("0")
        return (self._deposit_requirement_per_kg_usd * exposure_kg).quantize(Decimal("0.01"))

    def snapshot(
        self,
        available_balance_usd: Decimal,
        frozen_balance_usd: Decimal,
        floating_pnl_usd: Decimal,
        exposure_kg: Decimal,
        margin_balance_usd: Decimal = Decimal("0"),
        *,
        leverage: Decimal | None = None,
        maintenance_margin_ratio: Decimal | None = None,
        realized_pnl_usd: Decimal = Decimal("0"),
        mark_price_usd: Decimal | None = None,
        average_entry_price_usd: Decimal | None = None,
        margin_mode: MarginMode = MarginMode.cross,
    ) -> MarginSnapshot:
        effective_leverage = leverage if leverage is not None and leverage > 0 else self._default_max_leverage
        effective_maintenance_ratio = (
            maintenance_margin_ratio if maintenance_margin_ratio is not None and maintenance_margin_ratio > 0 else Decimal("1")
        )
        equity_usd = (available_balance_usd + frozen_balance_usd + margin_balance_usd + floating_pnl_usd).quantize(Decimal("0.01"))
        initial_margin_usd = self.required_deposit_usd(exposure_kg)
        maintenance_margin_usd = (initial_margin_usd * effective_maintenance_ratio).quantize(Decimal("0.01"))
        used_margin_usd = initial_margin_usd
        free_margin_usd = (equity_usd - used_margin_usd).quantize(Decimal("0.01"))
        available_margin_usd = (equity_usd - maintenance_margin_usd).quantize(Decimal("0.01"))
        exposure_notional_usd = Decimal("0")
        if mark_price_usd is not None and exposure_kg > 0:
            exposure_notional_usd = (exposure_kg * mark_price_usd).quantize(Decimal("0.01"))
        margin_utilization = Decimal("0")
        if equity_usd > 0 and used_margin_usd > 0:
            margin_utilization = (used_margin_usd / equity_usd).quantize(Decimal("0.0001"))
        if used_margin_usd <= 0:
            margin_ratio = Decimal("999999")
        else:
            margin_ratio = (equity_usd / used_margin_usd).quantize(Decimal("0.0001"))
        if margin_ratio <= self._liquidation_ratio_threshold:
            health = MarginAlertLevel.liquidation
        elif margin_ratio < self._maintenance_ratio_threshold:
            health = MarginAlertLevel.call
        elif margin_ratio < self._warning_ratio_threshold:
            health = MarginAlertLevel.warning
        else:
            health = MarginAlertLevel.normal
        liquidation_price_usd: Decimal | None = None
        if exposure_kg > 0 and average_entry_price_usd is not None and mark_price_usd is not None:
            pnl_buffer = equity_usd - maintenance_margin_usd
            per_kg_buffer = (pnl_buffer / exposure_kg).quantize(Decimal("0.000001"))
            if per_kg_buffer >= 0:
                liquidation_price_usd = (mark_price_usd - per_kg_buffer).quantize(Decimal("0.000001"))
        return MarginSnapshot(
            margin_mode=margin_mode,
            exposure_kg=exposure_kg.quantize(Decimal("0.000001")),
            available_balance_usd=available_balance_usd.quantize(Decimal("0.01")),
            frozen_balance_usd=frozen_balance_usd.quantize(Decimal("0.01")),
            margin_balance_usd=margin_balance_usd.quantize(Decimal("0.01")),
            equity_usd=equity_usd,
            initial_margin_usd=initial_margin_usd,
            maintenance_margin_usd=maintenance_margin_usd,
            used_margin_usd=used_margin_usd,
            free_margin_usd=free_margin_usd,
            available_margin_usd=available_margin_usd,
            margin_utilization=margin_utilization,
            margin_ratio=margin_ratio,
            leverage=effective_leverage,
            liquidation_price_usd=liquidation_price_usd,
            health=health,
            floating_pnl_usd=floating_pnl_usd.quantize(Decimal("0.01")),
            realized_pnl_usd=realized_pnl_usd.quantize(Decimal("0.01")),
            unrealized_pnl_usd=floating_pnl_usd.quantize(Decimal("0.01")),
        )

    def is_margin_call(self, snapshot: MarginSnapshot) -> bool:
        return snapshot.margin_ratio < self._maintenance_ratio_threshold

    def is_warning(self, snapshot: MarginSnapshot) -> bool:
        return snapshot.health in {MarginAlertLevel.warning, MarginAlertLevel.call, MarginAlertLevel.liquidation}

    def should_liquidate(self, snapshot: MarginSnapshot) -> bool:
        return snapshot.health == MarginAlertLevel.liquidation
