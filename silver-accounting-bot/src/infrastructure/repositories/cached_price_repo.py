from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from infrastructure.redis.cache import PriceCache
from infrastructure.repositories.sql_repos import SqlPriceRepo


class CachedPriceRepo:
    def __init__(self, inner: SqlPriceRepo, cache: PriceCache) -> None:
        self._inner = inner
        self._cache = cache

    async def get_latest(self, *, valid_only: bool = True) -> dict | None:
        cached = await self._cache.get()
        if cached is not None and (not valid_only or (cached.get("is_verified", True) and not cached.get("is_stale", False))):
            return cached
        row = await self._inner.get_latest(valid_only=valid_only)
        if row is not None:
            await self._cache.set(row)
        return row

    async def get_last_good(self) -> dict | None:
        cached = await self._cache.get()
        if cached is not None and cached.get("is_verified", True) and not cached.get("is_stale", False):
            return cached
        row = await self._inner.get_last_good()
        if row is not None:
            await self._cache.set(row)
        return row

    async def upsert(
        self,
        buy_price: Decimal,
        sell_price: Decimal,
        spread: Decimal,
        commission: Decimal,
        premium: Decimal,
        discount: Decimal,
        *,
        source: str = "manual_admin",
        external_id: str | None = None,
        provider_timestamp: datetime | None = None,
        is_verified: bool = True,
        is_stale: bool = False,
        raw_payload: str | None = None,
    ) -> dict:
        row = await self._inner.upsert(
            buy_price=buy_price,
            sell_price=sell_price,
            spread=spread,
            commission=commission,
            premium=premium,
            discount=discount,
            source=source,
            external_id=external_id,
            provider_timestamp=provider_timestamp,
            is_verified=is_verified,
            is_stale=is_stale,
            raw_payload=raw_payload,
        )
        if row.get("is_verified", True) and not row.get("is_stale", False):
            await self._cache.set(row)
        return row

    async def is_duplicate(
        self,
        *,
        source: str,
        buy_price: Decimal,
        sell_price: Decimal,
        provider_timestamp: datetime | None,
        window_seconds: int = 60,
    ) -> bool:
        return await self._inner.is_duplicate(
            source=source,
            buy_price=buy_price,
            sell_price=sell_price,
            provider_timestamp=provider_timestamp,
            window_seconds=window_seconds,
        )

    async def set_provider_status(
        self,
        *,
        provider_name: str,
        is_healthy: bool,
        checked_at: datetime,
        error: str | None = None,
        last_price_usd_per_kg: Decimal | None = None,
    ) -> dict:
        return await self._inner.set_provider_status(
            provider_name=provider_name,
            is_healthy=is_healthy,
            checked_at=checked_at,
            error=error,
            last_price_usd_per_kg=last_price_usd_per_kg,
        )
