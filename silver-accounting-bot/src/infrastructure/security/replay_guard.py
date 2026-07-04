from __future__ import annotations

import hashlib
import hmac
import json
import time

from redis.asyncio import Redis


class ReplayGuard:
    def __init__(self, redis: Redis, prefix: str = "nonce") -> None:
        self._redis = redis
        self._prefix = prefix

    async def check_nonce(self, nonce: str, ttl: int = 300) -> bool:
        key = f"{self._prefix}:{nonce}"
        exists = await self._redis.exists(key)
        return not bool(exists)

    async def mark_used(self, nonce: str, ttl: int = 300) -> None:
        key = f"{self._prefix}:{nonce}"
        await self._redis.set(key, "1", ex=ttl)

    async def validate_request(
        self,
        timestamp: str,
        nonce: str,
        signature: str,
        secret: str,
        payload: dict,
    ) -> bool:
        try:
            ts = int(timestamp)
            now = int(time.time())
            if abs(now - ts) > 300:
                return False
        except (ValueError, TypeError):
            return False

        key = f"{self._prefix}:{nonce}"
        stored = await self._redis.set(key, "1", nx=True, ex=300)
        if not stored:
            return False

        message = f"{timestamp}:{nonce}:{json.dumps(payload, sort_keys=True)}"
        expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            await self._redis.delete(key)
            return False

        return True
