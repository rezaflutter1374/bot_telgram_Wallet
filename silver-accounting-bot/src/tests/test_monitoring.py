from __future__ import annotations

import pytest

from infrastructure.monitoring.health import HealthChecker, HealthStatus


@pytest.mark.asyncio
async def test_health_checker_all_healthy() -> None:
    checker = HealthChecker()

    async def db_ok():
        return True, "ok"

    async def redis_ok():
        return True, "ok"

    checker.register("database", db_ok)
    checker.register("redis", redis_ok)

    status = await checker.check_all()
    assert status.healthy is True
    assert status.checks == {"database": True, "redis": True}


@pytest.mark.asyncio
async def test_health_checker_one_failure() -> None:
    checker = HealthChecker()

    async def db_ok():
        return True, "ok"

    async def redis_down():
        return False, "connection refused"

    checker.register("database", db_ok)
    checker.register("redis", redis_down)

    status = await checker.check_all()
    assert status.healthy is False
    assert status.checks == {"database": True, "redis": False}
    assert status.details["redis"] == "connection refused"


@pytest.mark.asyncio
async def test_health_checker_exception_handling() -> None:
    checker = HealthChecker()

    async def crash():
        raise RuntimeError("boom")

    checker.register("crashy", crash)

    status = await checker.check_all()
    assert status.healthy is False
    assert status.checks["crashy"] is False
    assert "boom" in status.details["crashy"]
