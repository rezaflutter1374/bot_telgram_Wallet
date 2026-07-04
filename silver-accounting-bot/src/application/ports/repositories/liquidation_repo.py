from __future__ import annotations

from decimal import Decimal
from typing import Protocol


class LiquidationRepo(Protocol):
    async def create_event(
        self,
        user_id: int,
        margin_ratio: Decimal,
        critical_level: Decimal,
        status: str,
    ) -> dict: ...

    async def get_event(self, event_id: int) -> dict | None: ...

    async def list_events(
        self, user_id: int | None = None, status: str | None = None, limit: int = 50
    ) -> list[dict]: ...

    async def update_status(
        self, event_id: int, status: str, close_price_usd: Decimal | None = None
    ) -> dict: ...

    async def get_insurance_balance(self) -> Decimal: ...

    async def debit_insurance(self, amount_usd: Decimal, reason: str) -> None: ...

    async def credit_insurance(self, amount_usd: Decimal, reason: str) -> None: ...
