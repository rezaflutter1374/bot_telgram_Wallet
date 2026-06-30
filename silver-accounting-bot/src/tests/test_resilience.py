from __future__ import annotations

from decimal import Decimal

import pytest

from domain.enums import CircuitBreakerState, RiskScoreLevel
from domain.services.risk_calc import RiskCalculator
from infrastructure.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitBreakerOpenError, CircuitBreakerRegistry
from infrastructure.resilience.retry import RetryConfig, async_retry


@pytest.mark.asyncio
async def test_circuit_breaker_closed_by_default() -> None:
    cb = CircuitBreaker("test", CircuitBreakerConfig(error_threshold=2, recovery_timeout_seconds=600))
    assert cb.state == CircuitBreakerState.closed
    assert cb.failure_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold() -> None:
    cb = CircuitBreaker("test", CircuitBreakerConfig(error_threshold=2, recovery_timeout_seconds=600))

    async def fail():
        raise ValueError("fail")

    for _ in range(2):
        with pytest.raises(ValueError):
            await cb.call(fail)

    assert cb.state == CircuitBreakerState.open

    with pytest.raises(CircuitBreakerOpenError):
        await cb.call(fail)


@pytest.mark.asyncio
async def test_circuit_breaker_success_resets() -> None:
    cb = CircuitBreaker("test", CircuitBreakerConfig(error_threshold=1, recovery_timeout_seconds=0.01))

    async def fail():
        raise ValueError("fail")

    async def succeed():
        return "ok"

    with pytest.raises(ValueError):
        await cb.call(fail)
    assert cb.state == CircuitBreakerState.open

    import asyncio
    await asyncio.sleep(0.02)

    result = await cb.call(succeed)
    assert result == "ok"
    assert cb.state == CircuitBreakerState.closed
    assert cb.failure_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_registry() -> None:
    registry = CircuitBreakerRegistry()
    cb = registry.get("svc_a", CircuitBreakerConfig(error_threshold=3))
    assert cb.name == "svc_a"
    assert registry.get("svc_a") is cb

    states = await registry.all_states()
    assert len(states) == 1
    assert states[0]["circuit_name"] == "svc_a"

    await registry.reset("svc_a")
    assert "svc_a" not in registry._breakers


@pytest.mark.asyncio
async def test_retry_success() -> None:
    calls = 0

    async def work():
        nonlocal calls
        calls += 1
        if calls < 2:
            raise ValueError("transient")
        return "done"

    config = RetryConfig(max_retries=2, base_delay_seconds=0.01)
    decorated = async_retry(config)(work)
    result = await decorated()
    assert result == "done"
    assert calls == 2


@pytest.mark.asyncio
async def test_retry_failure_exhausted() -> None:
    calls = 0

    async def always_fail():
        nonlocal calls
        calls += 1
        raise ValueError("persistent")

    config = RetryConfig(max_retries=2, base_delay_seconds=0.01)
    decorated = async_retry(config)(always_fail)
    with pytest.raises(ValueError, match="persistent"):
        await decorated()
    assert calls == 3


def test_risk_calculator_low_score() -> None:
    calc = RiskCalculator()
    exposure = {"leverage": "0.5", "exposure_kg": "1", "floating_pnl_usd": "0", "equity_usd": "10000"}
    score, level = calc.compute_score(exposure, [])
    assert level == RiskScoreLevel.low
    assert score < Decimal("10")


def test_risk_calculator_extreme_score() -> None:
    calc = RiskCalculator()
    exposure = {"leverage": "5", "exposure_kg": "200", "floating_pnl_usd": "-5000", "equity_usd": "1000"}
    violations = [
        {"severity": "critical", "violation_type": "max_leverage"},
        {"severity": "critical", "violation_type": "max_exposure"},
        {"severity": "warning", "violation_type": "concentration"},
    ]
    score, level = calc.compute_score(exposure, violations)
    assert level in {RiskScoreLevel.high, RiskScoreLevel.extreme}
    assert score >= Decimal("60")


def test_risk_calculator_with_violations() -> None:
    calc = RiskCalculator()
    exposure = {"leverage": "1", "exposure_kg": "5", "floating_pnl_usd": "0", "equity_usd": "5000"}
    violations = [{"severity": "warning", "violation_type": "concentration"}, {"severity": "warning", "violation_type": "drawdown"}]
    score, level = calc.compute_score(exposure, violations)
    assert level == RiskScoreLevel.low
    assert score >= Decimal("6")


def test_risk_calculator_high_loss() -> None:
    calc = RiskCalculator()
    exposure = {"leverage": "2", "exposure_kg": "10", "floating_pnl_usd": "-400", "equity_usd": "500"}
    score, level = calc.compute_score(exposure, [])
    assert level == RiskScoreLevel.high
