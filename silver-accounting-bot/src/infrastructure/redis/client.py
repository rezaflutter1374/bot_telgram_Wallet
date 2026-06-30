from __future__ import annotations

from redis.asyncio import Redis
from redis.asyncio import from_url


def create_redis(redis_url: str, *, max_connections: int = 100) -> Redis:
    return from_url(
        redis_url,
        decode_responses=True,
        max_connections=max_connections,
        health_check_interval=30,
        socket_timeout=5,
        socket_connect_timeout=5,
        retry_on_timeout=True,
    )
