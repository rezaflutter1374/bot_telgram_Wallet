from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text


@dataclass
class HealthStatus:
    healthy: bool
    checks: dict[str, bool] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


HealthCheckFunc = Callable[[], Awaitable[tuple[bool, str]]]


async def check_database(db) -> tuple[bool, str]:
    try:
        async with db.session() as session:
            await session.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


async def check_redis(redis) -> tuple[bool, str]:
    try:
        pong = await redis.ping()
        return bool(pong), "ok" if pong else "no_pong"
    except Exception as exc:
        return False, str(exc)


class HealthChecker:
    def __init__(self) -> None:
        self._checks: dict[str, HealthCheckFunc] = {}

    def register(self, name: str, check: HealthCheckFunc) -> None:
        self._checks[name] = check

    async def check_all(self) -> HealthStatus:
        status = HealthStatus(healthy=True)
        for name, check in self._checks.items():
            try:
                ok, detail = await check()
                status.checks[name] = ok
                status.details[name] = detail
                if not ok:
                    status.healthy = False
            except Exception as exc:
                status.checks[name] = False
                status.details[name] = str(exc)
                status.healthy = False
        return status
