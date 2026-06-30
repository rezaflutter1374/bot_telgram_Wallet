from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal

from redis.asyncio import Redis


class PriceCache:
    def __init__(self, redis: Redis, key: str = "prices:latest", ttl_seconds: int = 5) -> None:
        self._redis = redis
        self._key = key
        self._ttl_seconds = ttl_seconds

    async def get(self) -> dict | None:
        raw = await self._redis.get(self._key)
        if raw is None:
            return None
        data = json.loads(raw)
        for k in ("buy_price", "sell_price", "spread", "commission", "premium", "discount"):
            if k in data and data[k] is not None:
                data[k] = Decimal(str(data[k]))
        for k in ("updated_at", "provider_timestamp"):
            if k in data and data[k]:
                data[k] = datetime.fromisoformat(str(data[k]).replace("Z", "+00:00"))
        return data

    async def set(self, price_row: dict, ttl: timedelta | None = None) -> None:
        payload = dict(price_row)
        for k in ("buy_price", "sell_price", "spread", "commission", "premium", "discount"):
            if k in payload and payload[k] is not None:
                payload[k] = str(payload[k])
        for k in ("updated_at", "provider_timestamp"):
            if k in payload and payload[k] is not None:
                payload[k] = payload[k].isoformat() if hasattr(payload[k], "isoformat") else str(payload[k])
        effective_ttl = ttl or timedelta(seconds=self._ttl_seconds)
        await self._redis.set(self._key, json.dumps(payload, ensure_ascii=False), ex=int(effective_ttl.total_seconds()))
