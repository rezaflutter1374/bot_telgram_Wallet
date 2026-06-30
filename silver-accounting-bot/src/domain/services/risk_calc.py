from __future__ import annotations

from decimal import Decimal

from domain.enums import RiskScoreLevel


class RiskCalculator:
    def compute_score(self, exposure: dict, violations: list[dict]) -> tuple[Decimal, RiskScoreLevel]:
        raw_score = Decimal("0")
        leverage = Decimal(str(exposure.get("leverage", "0")))
        exposure_kg = Decimal(str(exposure.get("exposure_kg", "0")))
        floating_pnl = Decimal(str(exposure.get("floating_pnl_usd", "0")))
        equity = Decimal(str(exposure.get("equity_usd", "0")))

        if leverage > Decimal("3"):
            raw_score += Decimal("25")
        elif leverage > Decimal("2"):
            raw_score += Decimal("15")
        elif leverage > Decimal("1"):
            raw_score += Decimal("5")

        if exposure_kg > Decimal("100"):
            raw_score += Decimal("20")
        elif exposure_kg > Decimal("50"):
            raw_score += Decimal("10")
        elif exposure_kg > Decimal("10"):
            raw_score += Decimal("5")

        if equity > 0 and floating_pnl < Decimal("0"):
            loss_pct = abs(floating_pnl) / equity
            if loss_pct > Decimal("0.5"):
                raw_score += Decimal("30")
            elif loss_pct > Decimal("0.25"):
                raw_score += Decimal("15")
            else:
                raw_score += Decimal("5")

        critical_count = sum(1 for v in violations if v.get("severity", "").lower() == "critical")
        warning_count = sum(1 for v in violations if v.get("severity", "").lower() == "warning")
        raw_score += Decimal(str(critical_count * 10))
        raw_score += Decimal(str(warning_count * 3))

        if raw_score >= Decimal("60"):
            level = RiskScoreLevel.extreme
        elif raw_score >= Decimal("30"):
            level = RiskScoreLevel.high
        elif raw_score >= Decimal("10"):
            level = RiskScoreLevel.medium
        else:
            level = RiskScoreLevel.low

        return raw_score.quantize(Decimal("0.01")), level
