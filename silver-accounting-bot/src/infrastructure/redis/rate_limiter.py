from __future__ import annotations

from datetime import timedelta

from redis.asyncio import Redis


class RateLimiter:
    def __init__(self, redis: Redis, prefix: str = "rate") -> None:
        self._redis = redis
        self._prefix = prefix

    async def allow(self, key: str, limit: int, window: timedelta) -> bool:
        bucket = f"{self._prefix}:{key}"
        count = await self._redis.incr(bucket, 1)
        if count == 1:
            await self._redis.expire(bucket, int(window.total_seconds()))
        return int(count) <= limit
