from __future__ import annotations

from decimal import Decimal

import pytest

from domain.enums import RiskViolationSeverity
from domain.services.risk_engine import RiskEngine


@pytest.fixture
def engine() -> RiskEngine:
    return RiskEngine()


class TestCheckPositionLimit:
    def test_under_limit_passes(self, engine: RiskEngine):
        result = engine.check_position_limit(
            current_net_kg=Decimal("10"),
            proposed_delta_kg=Decimal("5"),
            limit=Decimal("100"),
        )
        assert result.passed is True

    def test_over_limit_fails(self, engine: RiskEngine):
        result = engine.check_position_limit(
            current_net_kg=Decimal("80"),
            proposed_delta_kg=Decimal("30"),
            limit=Decimal("100"),
        )
        assert result.passed is False
        assert result.limit_type.value == "position"
        assert result.current_value == Decimal("110")
        assert result.max_value == Decimal("100")

    def test_exact_limit_passes(self, engine: RiskEngine):
        result = engine.check_position_limit(
            current_net_kg=Decimal("70"),
            proposed_delta_kg=Decimal("30"),
            limit=Decimal("100"),
        )
        assert result.passed is True

    def test_zero_limit_disabled(self, engine: RiskEngine):
        result = engine.check_position_limit(
            current_net_kg=Decimal("1000"),
            proposed_delta_kg=Decimal("500"),
            limit=Decimal("0"),
        )
        assert result.passed is True

    def test_reducing_position_under_limit(self, engine: RiskEngine):
        result = engine.check_position_limit(
            current_net_kg=Decimal("10"),
            proposed_delta_kg=Decimal("-9"),
            limit=Decimal("3"),
        )
        assert result.passed is True


class TestCheckExposureLimit:
    def test_under_exposure_limit_passes(self, engine: RiskEngine):
        result = engine.check_exposure_limit(
            current_exposure_kg=Decimal("50"),
            proposed_additional_kg=Decimal("10"),
            limit=Decimal("100"),
        )
        assert result.passed is True

    def test_over_exposure_limit_fails(self, engine: RiskEngine):
        result = engine.check_exposure_limit(
            current_exposure_kg=Decimal("80"),
            proposed_additional_kg=Decimal("30"),
            limit=Decimal("100"),
        )
        assert result.passed is False
        assert result.max_value == Decimal("100")

    def test_exact_exposure_limit_passes(self, engine: RiskEngine):
        result = engine.check_exposure_limit(
            current_exposure_kg=Decimal("80"),
            proposed_additional_kg=Decimal("20"),
            limit=Decimal("100"),
        )
        assert result.passed is True

    def test_zero_exposure_limit_disabled(self, engine: RiskEngine):
        result = engine.check_exposure_limit(
            current_exposure_kg=Decimal("1000"),
            proposed_additional_kg=Decimal("500"),
            limit=Decimal("0"),
        )
        assert result.passed is True

    def test_negative_current_exposure(self, engine: RiskEngine):
        result = engine.check_exposure_limit(
            current_exposure_kg=Decimal("-50"),
            proposed_additional_kg=Decimal("30"),
            limit=Decimal("100"),
        )
        assert result.passed is True


class TestCheckDailyLossLimit:
    def test_under_loss_limit_passes(self, engine: RiskEngine):
        result = engine.check_daily_loss_limit(
            current_daily_loss_usd=Decimal("100"),
            proposed_loss_usd=Decimal("50"),
            limit=Decimal("1000"),
        )
        assert result.passed is True

    def test_over_loss_limit_fails(self, engine: RiskEngine):
        result = engine.check_daily_loss_limit(
            current_daily_loss_usd=Decimal("900"),
            proposed_loss_usd=Decimal("200"),
            limit=Decimal("1000"),
        )
        assert result.passed is False
        assert result.severity == RiskViolationSeverity.warning

    def test_zero_loss_limit_disabled(self, engine: RiskEngine):
        result = engine.check_daily_loss_limit(
            current_daily_loss_usd=Decimal("10000"),
            proposed_loss_usd=Decimal("5000"),
            limit=Decimal("0"),
        )
        assert result.passed is True

    def test_zero_proposed_loss(self, engine: RiskEngine):
        result = engine.check_daily_loss_limit(
            current_daily_loss_usd=Decimal("500"),
            proposed_loss_usd=Decimal("0"),
            limit=Decimal("1000"),
        )
        assert result.passed is True


class TestCheckVolumeLimit:
    def test_under_volume_limit_passes(self, engine: RiskEngine):
        result = engine.check_volume_limit(
            daily_volume_kg=Decimal("500"),
            proposed_volume_kg=Decimal("100"),
            limit=Decimal("1000"),
        )
        assert result.passed is True

    def test_over_volume_limit_fails(self, engine: RiskEngine):
        result = engine.check_volume_limit(
            daily_volume_kg=Decimal("900"),
            proposed_volume_kg=Decimal("200"),
            limit=Decimal("1000"),
        )
        assert result.passed is False
        assert result.severity == RiskViolationSeverity.warning

    def test_zero_volume_limit_disabled(self, engine: RiskEngine):
        result = engine.check_volume_limit(
            daily_volume_kg=Decimal("5000"),
            proposed_volume_kg=Decimal("2000"),
            limit=Decimal("0"),
        )
        assert result.passed is True


class TestCheckMaxDrawdown:
    def test_under_drawdown_passes(self, engine: RiskEngine):
        result = engine.check_max_drawdown(
            peak_equity_usd=Decimal("10000"),
            current_equity_usd=Decimal("9500"),
            max_drawdown_usd=Decimal("1000"),
        )
        assert result.passed is True

    def test_over_drawdown_fails(self, engine: RiskEngine):
        result = engine.check_max_drawdown(
            peak_equity_usd=Decimal("10000"),
            current_equity_usd=Decimal("8000"),
            max_drawdown_usd=Decimal("1000"),
        )
        assert result.passed is False
        assert result.severity == RiskViolationSeverity.critical

    def test_zero_drawdown_limit_disabled(self, engine: RiskEngine):
        result = engine.check_max_drawdown(
            peak_equity_usd=Decimal("10000"),
            current_equity_usd=Decimal("1000"),
            max_drawdown_usd=Decimal("0"),
        )
        assert result.passed is True

    def test_no_drawdown(self, engine: RiskEngine):
        result = engine.check_max_drawdown(
            peak_equity_usd=Decimal("10000"),
            current_equity_usd=Decimal("11000"),
            max_drawdown_usd=Decimal("1000"),
        )
        assert result.passed is True

    def test_exact_drawdown_passes(self, engine: RiskEngine):
        result = engine.check_max_drawdown(
            peak_equity_usd=Decimal("10000"),
            current_equity_usd=Decimal("9000"),
            max_drawdown_usd=Decimal("1000"),
        )
        assert result.passed is True


class TestCheckLeverageLimit:
    def test_under_leverage_limit_passes(self, engine: RiskEngine):
        result = engine.check_leverage_limit(
            notional_value_usd=Decimal("50000"),
            equity_usd=Decimal("10000"),
            max_leverage=Decimal("10"),
        )
        assert result.passed is True

    def test_over_leverage_limit_fails(self, engine: RiskEngine):
        result = engine.check_leverage_limit(
            notional_value_usd=Decimal("200000"),
            equity_usd=Decimal("10000"),
            max_leverage=Decimal("10"),
        )
        assert result.passed is False
        assert result.severity == RiskViolationSeverity.critical

    def test_zero_equity_skips_check(self, engine: RiskEngine):
        result = engine.check_leverage_limit(
            notional_value_usd=Decimal("100000"),
            equity_usd=Decimal("0"),
            max_leverage=Decimal("10"),
        )
        assert result.passed is True

    def test_zero_max_leverage_skips(self, engine: RiskEngine):
        result = engine.check_leverage_limit(
            notional_value_usd=Decimal("100000"),
            equity_usd=Decimal("10000"),
            max_leverage=Decimal("0"),
        )
        assert result.passed is True

    def test_exact_leverage_passes(self, engine: RiskEngine):
        result = engine.check_leverage_limit(
            notional_value_usd=Decimal("100000"),
            equity_usd=Decimal("10000"),
            max_leverage=Decimal("10"),
        )
        assert result.passed is True


class TestCheckConcentration:
    def test_under_concentration_passes(self, engine: RiskEngine):
        result = engine.check_concentration(
            position_value_usd=Decimal("10000"),
            total_pool_value_usd=Decimal("100000"),
            max_concentration=Decimal("0.2"),
        )
        assert result.passed is True

    def test_over_concentration_fails(self, engine: RiskEngine):
        result = engine.check_concentration(
            position_value_usd=Decimal("50000"),
            total_pool_value_usd=Decimal("100000"),
            max_concentration=Decimal("0.2"),
        )
        assert result.passed is False
        assert result.severity == RiskViolationSeverity.warning

    def test_zero_pool_value_skips(self, engine: RiskEngine):
        result = engine.check_concentration(
            position_value_usd=Decimal("10000"),
            total_pool_value_usd=Decimal("0"),
            max_concentration=Decimal("0.2"),
        )
        assert result.passed is True

    def test_zero_max_concentration_skips(self, engine: RiskEngine):
        result = engine.check_concentration(
            position_value_usd=Decimal("10000"),
            total_pool_value_usd=Decimal("100000"),
            max_concentration=Decimal("0"),
        )
        assert result.passed is True

    def test_exact_concentration_passes(self, engine: RiskEngine):
        result = engine.check_concentration(
            position_value_usd=Decimal("20000"),
            total_pool_value_usd=Decimal("100000"),
            max_concentration=Decimal("0.2"),
        )
        assert result.passed is True


class TestEvaluateAllLimits:
    def test_all_checks_pass(self, engine: RiskEngine):
        results = engine.evaluate_all_limits(
            current_net_kg=Decimal("10"),
            proposed_delta_kg=Decimal("5"),
            current_exposure_kg=Decimal("10"),
            daily_loss_usd=Decimal("100"),
            daily_volume_kg=Decimal("50"),
            peak_equity_usd=Decimal("10000"),
            current_equity_usd=Decimal("10000"),
            notional_value_usd=Decimal("1500"),
            position_value_usd=Decimal("1500"),
            total_pool_value_usd=Decimal("100000"),
        )
        assert len(results) == 0

    def test_some_checks_fail(self, engine: RiskEngine):
        results = engine.evaluate_all_limits(
            current_net_kg=Decimal("200"),
            proposed_delta_kg=Decimal("100"),
            current_exposure_kg=Decimal("200"),
            daily_loss_usd=Decimal("5000"),
            daily_volume_kg=Decimal("500"),
            peak_equity_usd=Decimal("10000"),
            current_equity_usd=Decimal("3000"),
            notional_value_usd=Decimal("30000"),
            position_value_usd=Decimal("30000"),
            total_pool_value_usd=Decimal("50000"),
            position_limit_kg=Decimal("100"),
            exposure_limit_kg=Decimal("100"),
            daily_loss_limit_usd=Decimal("1000"),
            volume_limit_kg=Decimal("200"),
            max_drawdown_usd=Decimal("1000"),
            max_leverage=Decimal("5"),
            max_concentration=Decimal("0.2"),
        )
        assert len(results) >= 1

    def test_all_checks_fail_worst_case(self, engine: RiskEngine):
        results = engine.evaluate_all_limits(
            current_net_kg=Decimal("100"),
            proposed_delta_kg=Decimal("100"),
            current_exposure_kg=Decimal("200"),
            daily_loss_usd=Decimal("10000"),
            daily_volume_kg=Decimal("1000"),
            peak_equity_usd=Decimal("10000"),
            current_equity_usd=Decimal("500"),
            notional_value_usd=Decimal("20000"),
            position_value_usd=Decimal("20000"),
            total_pool_value_usd=Decimal("10000"),
            position_limit_kg=Decimal("50"),
            exposure_limit_kg=Decimal("50"),
            daily_loss_limit_usd=Decimal("100"),
            volume_limit_kg=Decimal("100"),
            max_drawdown_usd=Decimal("100"),
            max_leverage=Decimal("2"),
            max_concentration=Decimal("0.05"),
        )
        limit_types = {r.limit_type.value for r in results}
        assert "position" in limit_types
        assert "exposure" in limit_types
        assert "daily_loss" in limit_types
        assert "volume" in limit_types
        assert "drawdown" in limit_types
        assert "leverage" in limit_types
        assert "concentration" in limit_types

    def test_empty_position_edge(self, engine: RiskEngine):
        results = engine.evaluate_all_limits(
            current_net_kg=Decimal("0"),
            proposed_delta_kg=Decimal("0"),
            current_exposure_kg=Decimal("0"),
            daily_loss_usd=Decimal("0"),
            daily_volume_kg=Decimal("0"),
            peak_equity_usd=Decimal("10000"),
            current_equity_usd=Decimal("10000"),
            notional_value_usd=Decimal("0"),
            position_value_usd=Decimal("0"),
            total_pool_value_usd=Decimal("100000"),
            position_limit_kg=Decimal("100"),
            exposure_limit_kg=Decimal("100"),
        )
        assert len(results) == 0

    def test_all_limits_zero_disabled(self, engine: RiskEngine):
        results = engine.evaluate_all_limits(
            current_net_kg=Decimal("1000"),
            proposed_delta_kg=Decimal("1000"),
            current_exposure_kg=Decimal("2000"),
            daily_loss_usd=Decimal("100000"),
            daily_volume_kg=Decimal("10000"),
            peak_equity_usd=Decimal("10000"),
            current_equity_usd=Decimal("1"),
            notional_value_usd=Decimal("100000"),
            position_value_usd=Decimal("100000"),
            total_pool_value_usd=Decimal("1"),
        )
        assert len(results) == 0

    def test_returns_only_failed_results(self, engine: RiskEngine):
        results = engine.evaluate_all_limits(
            current_net_kg=Decimal("200"),
            proposed_delta_kg=Decimal("0"),
            current_exposure_kg=Decimal("200"),
            daily_loss_usd=Decimal("100"),
            daily_volume_kg=Decimal("50"),
            peak_equity_usd=Decimal("10000"),
            current_equity_usd=Decimal("10000"),
            notional_value_usd=Decimal("0"),
            position_value_usd=Decimal("0"),
            total_pool_value_usd=Decimal("100000"),
            position_limit_kg=Decimal("100"),
        )
        assert all(not r.passed for r in results)
