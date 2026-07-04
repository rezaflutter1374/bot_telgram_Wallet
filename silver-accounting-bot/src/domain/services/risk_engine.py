from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, timedelta
from enum import Enum

from domain.enums import RiskViolationSeverity


class RiskLimitType(str, Enum):
    position = "position"
    exposure = "exposure"
    daily_loss = "daily_loss"
    volume = "volume"
    drawdown = "drawdown"
    leverage = "leverage"
    concentration = "concentration"


@dataclass(frozen=True)
class RiskLimit:
    limit_type: RiskLimitType
    max_value: Decimal
    enabled: bool = True
    block_trading: bool = True
    alert_threshold: Decimal | None = None  # e.g. 0.8 = 80% of limit


@dataclass(frozen=True)
class RiskCheckResult:
    passed: bool
    limit_type: RiskLimitType | None = None
    current_value: Decimal | None = None
    max_value: Decimal | None = None
    severity: RiskViolationSeverity | None = None
    message: str = ""


@dataclass(frozen=True)
class RiskSnapshot:
    user_id: int
    exposure_kg: Decimal
    daily_pnl_usd: Decimal
    daily_loss_usd: Decimal
    drawdown_usd: Decimal
    concentration_ratio: Decimal
    risk_score: Decimal
    risk_score_level: str
    violation_count: int
    timestamp: datetime = field(default_factory=lambda: datetime.now())
    payload: dict = field(default_factory=dict)


class RiskEngine:
    def check_position_limit(
        self,
        current_net_kg: Decimal,
        proposed_delta_kg: Decimal,
        limit: Decimal,
    ) -> RiskCheckResult:
        new_position = abs(current_net_kg + proposed_delta_kg)
        if limit > 0 and new_position > limit:
            return RiskCheckResult(
                passed=False,
                limit_type=RiskLimitType.position,
                current_value=new_position,
                max_value=limit,
                severity=RiskViolationSeverity.critical,
                message=f"Position limit {limit}kg exceeded: {new_position}kg",
            )
        return RiskCheckResult(passed=True)

    def check_exposure_limit(
        self,
        current_exposure_kg: Decimal,
        proposed_additional_kg: Decimal,
        limit: Decimal,
    ) -> RiskCheckResult:
        new_exposure = abs(current_exposure_kg) + abs(proposed_additional_kg)
        if limit > 0 and new_exposure > limit:
            return RiskCheckResult(
                passed=False,
                limit_type=RiskLimitType.exposure,
                current_value=new_exposure,
                max_value=limit,
                severity=RiskViolationSeverity.critical,
                message=f"Exposure limit {limit}kg exceeded: {new_exposure}kg",
            )
        return RiskCheckResult(passed=True)

    def check_daily_loss_limit(
        self,
        current_daily_loss_usd: Decimal,
        proposed_loss_usd: Decimal,
        limit: Decimal,
    ) -> RiskCheckResult:
        new_loss = current_daily_loss_usd + proposed_loss_usd
        if limit > 0 and new_loss > limit:
            return RiskCheckResult(
                passed=False,
                limit_type=RiskLimitType.daily_loss,
                current_value=new_loss,
                max_value=limit,
                severity=RiskViolationSeverity.warning,
                message=f"Daily loss limit {limit}USD exceeded: {new_loss}USD",
            )
        return RiskCheckResult(passed=True)

    def check_volume_limit(
        self,
        daily_volume_kg: Decimal,
        proposed_volume_kg: Decimal,
        limit: Decimal,
    ) -> RiskCheckResult:
        new_volume = daily_volume_kg + proposed_volume_kg
        if limit > 0 and new_volume > limit:
            return RiskCheckResult(
                passed=False,
                limit_type=RiskLimitType.volume,
                current_value=new_volume,
                max_value=limit,
                severity=RiskViolationSeverity.warning,
                message=f"Volume limit {limit}kg exceeded: {new_volume}kg",
            )
        return RiskCheckResult(passed=True)

    def check_max_drawdown(
        self,
        peak_equity_usd: Decimal,
        current_equity_usd: Decimal,
        max_drawdown_usd: Decimal,
    ) -> RiskCheckResult:
        drawdown = peak_equity_usd - current_equity_usd
        if max_drawdown_usd > 0 and drawdown > max_drawdown_usd:
            return RiskCheckResult(
                passed=False,
                limit_type=RiskLimitType.drawdown,
                current_value=drawdown,
                max_value=max_drawdown_usd,
                severity=RiskViolationSeverity.critical,
                message=f"Max drawdown {max_drawdown_usd}USD exceeded: {drawdown}USD",
            )
        return RiskCheckResult(passed=True)

    def check_leverage_limit(
        self,
        notional_value_usd: Decimal,
        equity_usd: Decimal,
        max_leverage: Decimal,
    ) -> RiskCheckResult:
        if equity_usd <= 0 or max_leverage <= 0:
            return RiskCheckResult(passed=True)
        current_leverage = (notional_value_usd / equity_usd).quantize(Decimal("0.01"))
        if current_leverage > max_leverage:
            return RiskCheckResult(
                passed=False,
                limit_type=RiskLimitType.leverage,
                current_value=current_leverage,
                max_value=max_leverage,
                severity=RiskViolationSeverity.critical,
                message=f"Leverage limit {max_leverage}x exceeded: {current_leverage}x",
            )
        return RiskCheckResult(passed=True)

    def check_concentration(
        self,
        position_value_usd: Decimal,
        total_pool_value_usd: Decimal,
        max_concentration: Decimal,
    ) -> RiskCheckResult:
        if total_pool_value_usd <= 0 or max_concentration <= 0:
            return RiskCheckResult(passed=True)
        ratio = (position_value_usd / total_pool_value_usd).quantize(Decimal("0.000001"))
        if ratio > max_concentration:
            return RiskCheckResult(
                passed=False,
                limit_type=RiskLimitType.concentration,
                current_value=ratio,
                max_value=max_concentration,
                severity=RiskViolationSeverity.warning,
                message=f"Concentration limit {max_concentration} exceeded: {ratio}",
            )
        return RiskCheckResult(passed=True)

    def evaluate_all_limits(
        self,
        *,
        current_net_kg: Decimal,
        proposed_delta_kg: Decimal,
        current_exposure_kg: Decimal,
        daily_loss_usd: Decimal,
        daily_volume_kg: Decimal,
        peak_equity_usd: Decimal,
        current_equity_usd: Decimal,
        notional_value_usd: Decimal,
        position_value_usd: Decimal,
        total_pool_value_usd: Decimal,
        position_limit_kg: Decimal = Decimal("0"),
        exposure_limit_kg: Decimal = Decimal("0"),
        daily_loss_limit_usd: Decimal = Decimal("0"),
        volume_limit_kg: Decimal = Decimal("0"),
        max_drawdown_usd: Decimal = Decimal("0"),
        max_leverage: Decimal = Decimal("0"),
        max_concentration: Decimal = Decimal("0"),
    ) -> list[RiskCheckResult]:
        results: list[RiskCheckResult] = []
        results.append(self.check_position_limit(current_net_kg, proposed_delta_kg, position_limit_kg))
        results.append(self.check_exposure_limit(current_exposure_kg, proposed_delta_kg, exposure_limit_kg))
        results.append(self.check_daily_loss_limit(daily_loss_usd, Decimal("0"), daily_loss_limit_usd))
        results.append(self.check_volume_limit(daily_volume_kg, abs(proposed_delta_kg), volume_limit_kg))
        results.append(self.check_max_drawdown(peak_equity_usd, current_equity_usd, max_drawdown_usd))
        results.append(self.check_leverage_limit(notional_value_usd, current_equity_usd, max_leverage))
        results.append(self.check_concentration(position_value_usd, total_pool_value_usd, max_concentration))
        return [r for r in results if not r.passed]
