from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from domain.enums import MarginMode
from domain.services.margin import MarginCalculator, MarginSnapshot


@dataclass(frozen=True)
class IsolatedMarginState:
    user_id: int
    position_net_kg: Decimal
    position_avg_price_usd: Decimal
    margin_balance_usd: Decimal
    leverage: Decimal
    liquidation_price_usd: Decimal | None


@dataclass(frozen=True)
class MarginRequirement:
    initial_margin_usd: Decimal
    maintenance_margin_usd: Decimal
    available_margin_usd: Decimal
    free_margin_usd: Decimal
    used_margin_usd: Decimal
    margin_ratio: Decimal


class MarginEngine:
    def __init__(self, margin_calculator: MarginCalculator):
        self._calculator = margin_calculator

    def calculate_requirements(
        self,
        exposure_kg: Decimal,
        equity_usd: Decimal,
        margin_balance_usd: Decimal,
        leverage: Decimal | None = None,
        maintenance_ratio: Decimal | None = None,
    ) -> MarginRequirement:
        initial = self._calculator.required_deposit_usd(exposure_kg)
        effective_leverage = leverage if leverage is not None and leverage > 0 else self._calculator._default_max_leverage
        effective_maintenance = maintenance_ratio if maintenance_ratio is not None and maintenance_ratio > 0 else self._calculator._maintenance_ratio_threshold
        maintenance = (initial * effective_maintenance).quantize(Decimal("0.01"))
        used = min(initial + maintenance, equity_usd) if exposure_kg > 0 else Decimal("0")
        free = (equity_usd - used).quantize(Decimal("0.01"))
        ratio = Decimal("999999")
        if used > 0:
            ratio = (equity_usd / used).quantize(Decimal("0.000001"))
        available = max(free, Decimal("0"))
        return MarginRequirement(
            initial_margin_usd=initial,
            maintenance_margin_usd=maintenance,
            available_margin_usd=available,
            free_margin_usd=free,
            used_margin_usd=used,
            margin_ratio=ratio,
        )

    def calculate_isolated_margin(
        self,
        position_net_kg: Decimal,
        position_avg_price_usd: Decimal,
        margin_allocated_usd: Decimal,
        leverage: Decimal,
        mark_price_usd: Decimal,
    ) -> IsolatedMarginState:
        if position_net_kg == 0 or leverage <= 0:
            liq_price = None
        elif position_net_kg > 0:
            liq_price = position_avg_price_usd * (Decimal("1") - Decimal("1") / leverage)
        else:
            liq_price = position_avg_price_usd * (Decimal("1") + Decimal("1") / leverage)
        if liq_price is not None and liq_price <= 0:
            liq_price = Decimal("0.000001")
        return IsolatedMarginState(
            user_id=0,
            position_net_kg=position_net_kg,
            position_avg_price_usd=position_avg_price_usd,
            margin_balance_usd=margin_allocated_usd,
            leverage=leverage,
            liquidation_price_usd=liq_price.quantize(Decimal("0.000001")) if liq_price else None,
        )

    def calculate_funding_fee(
        self,
        position_net_kg: Decimal,
        mark_price_usd: Decimal,
        funding_rate: Decimal,
    ) -> Decimal:
        return (position_net_kg * mark_price_usd * funding_rate).quantize(Decimal("0.01"))

    def validate_margin_sufficient(
        self,
        required_margin_usd: Decimal,
        available_balance_usd: Decimal,
        frozen_balance_usd: Decimal,
        margin_balance_usd: Decimal,
    ) -> tuple[bool, str]:
        total_available = available_balance_usd + frozen_balance_usd + margin_balance_usd
        if total_available < required_margin_usd:
            return False, f"Insufficient margin: need {required_margin_usd}, have {total_available}"
        return True, ""

    def estimate_max_position(
        self,
        available_balance_usd: Decimal,
        current_exposure_kg: Decimal,
        price_usd: Decimal,
        leverage: Decimal,
    ) -> Decimal:
        return self._calculator.estimate_max_position_kg(
            available_balance_usd=available_balance_usd,
            current_exposure_kg=current_exposure_kg,
            price_usd=price_usd,
            leverage=leverage,
        )

    def margin_call_ratio(self, snapshot: MarginSnapshot) -> Decimal:
        return (snapshot.equity_usd / snapshot.maintenance_margin_usd).quantize(Decimal("0.000001")) if snapshot.maintenance_margin_usd > 0 else Decimal("999999")

    def is_margin_call(self, snapshot: MarginSnapshot, threshold: Decimal = Decimal("1")) -> bool:
        return self.margin_call_ratio(snapshot) < threshold

    def is_liquidation(self, snapshot: MarginSnapshot, threshold: Decimal = Decimal("0.5")) -> bool:
        return self.margin_call_ratio(snapshot) < threshold
