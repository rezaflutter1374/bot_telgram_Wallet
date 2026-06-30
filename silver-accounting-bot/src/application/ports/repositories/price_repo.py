from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol


class PriceRepo(Protocol):
    async def get_latest(self, *, valid_only: bool = True) -> dict | None: ...

    async def get_last_good(self) -> dict | None: ...

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
    ) -> dict: ...

    async def is_duplicate(
        self,
        *,
        source: str,
        buy_price: Decimal,
        sell_price: Decimal,
        provider_timestamp: datetime | None,
        window_seconds: int = 60,
    ) -> bool: ...

    async def set_provider_status(
        self,
        *,
        provider_name: str,
        is_healthy: bool,
        checked_at: datetime,
        error: str | None = None,
        last_price_usd_per_kg: Decimal | None = None,
    ) -> dict: ...

    async def detect_anomaly(
        self,
        *,
        anomaly_type: str,
        severity: str,
        observed_value_usd: Decimal,
        expected_value_usd: Decimal,
        deviation_pct: Decimal,
        threshold_pct: Decimal,
        price_id: int,
        payload: dict | None = None,
    ) -> dict | None: ...

    async def list_anomalies(
        self,
        *,
        anomaly_type: str | None = None,
        is_resolved: bool | None = None,
        limit: int = 50,
    ) -> list[dict]: ...

    async def resolve_anomaly(self, anomaly_id: int, resolved_by_user_id: int) -> dict | None: ...

    async def get_price_history(self, limit: int = 20) -> list[dict]: ...
