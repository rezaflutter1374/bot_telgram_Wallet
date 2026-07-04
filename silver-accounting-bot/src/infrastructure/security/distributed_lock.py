from __future__ import annotations

import asyncio
import time
import uuid

from redis.asyncio import Redis

_UNLOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class LockAcquisitionError(Exception):
    pass


class DistributedLock:
    def __init__(self, redis: Redis, name: str, timeout: int = 10, blocking: bool = False) -> None:
        self._redis = redis
        self._name = name
        self._timeout = timeout
        self._blocking = blocking
        self._token: str | None = None
        self._tokens: dict[str, str] = {}

    async def acquire(self, name: str, timeout: int = 10, blocking: bool = False) -> bool:
        key = f"lock:{name}"
        token = str(uuid.uuid4())

        if blocking:
            deadline = time.monotonic() + timeout
            backoff = 0.1
            while time.monotonic() < deadline:
                acquired = await self._redis.set(key, token, nx=True, ex=timeout)
                if acquired:
                    self._tokens[name] = token
                    return True
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 1.0)
            return False

        acquired = await self._redis.set(key, token, nx=True, ex=timeout)
        if acquired:
            self._tokens[name] = token
            return True
        return False

    async def release(self, name: str) -> None:
        key = f"lock:{name}"
        token = self._tokens.pop(name, None)
        if token:
            await self._redis.eval(_UNLOCK_SCRIPT, 1, key, token)

    async def __aenter__(self) -> DistributedLock:
        self._token = str(uuid.uuid4())
        key = f"lock:{self._name}"

        if self._blocking:
            deadline = time.monotonic() + self._timeout
            backoff = 0.1
            while time.monotonic() < deadline:
                if await self._redis.set(key, self._token, nx=True, ex=self._timeout):
                    return self
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 1.0)
            raise LockAcquisitionError(f"Could not acquire lock: {self._name}")

        if not await self._redis.set(key, self._token, nx=True, ex=self._timeout):
            raise LockAcquisitionError(f"Could not acquire lock: {self._name}")
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._token:
            key = f"lock:{self._name}"
            await self._redis.eval(_UNLOCK_SCRIPT, 1, key, self._token)
            self._token = None
