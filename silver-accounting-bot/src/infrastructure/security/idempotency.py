from __future__ import annotations

import time

from redis.asyncio import Redis


class IdempotencyGuard:
    def __init__(self, redis: Redis, prefix: str = "idemp") -> None:
        self._redis = redis
        self._prefix = prefix

    async def check_and_set(self, key: str, ttl_seconds: int = 86400) -> bool:
        redis_key = f"{self._prefix}:{key}"
        added = await self._redis.set(redis_key, "1", nx=True, ex=ttl_seconds)
        if added:
            expiry = int(time.time()) + ttl_seconds
            await self._redis.zadd(f"{self._prefix}:index", {redis_key: expiry})
            return False
        return True

    async def cleanup_expired(self) -> None:
        now = time.time()
        index_key = f"{self._prefix}:index"
        expired = await self._redis.zrangebyscore(index_key, 0, now)
        if expired:
            await self._redis.delete(*expired)
            await self._redis.zremrangebyscore(index_key, 0, now)
