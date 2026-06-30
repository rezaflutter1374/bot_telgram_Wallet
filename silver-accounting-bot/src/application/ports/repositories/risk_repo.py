from __future__ import annotations

from decimal import Decimal
from typing import Protocol


class RiskRepo(Protocol):
    async def get_active_rule(self) -> dict | None: ...

    async def upsert_rule(
        self,
        name: str,
        max_user_exposure_kg: Decimal,
        max_order_kg: Decimal,
        enabled: bool,
        *,
        max_daily_loss_usd: Decimal = Decimal("0"),
        max_leverage: Decimal = Decimal("0"),
        max_concentration_ratio: Decimal = Decimal("0"),
        max_drawdown_usd: Decimal = Decimal("0"),
        block_trading_on_violation: bool = True,
    ) -> dict: ...

    async def create_violation(
        self,
        *,
        user_id: int | None,
        order_id: int | None,
        severity: str,
        violation_type: str,
        message: str,
        payload: dict,
    ) -> dict: ...

    async def list_open_violations(self, *, user_id: int | None = None, limit: int = 100) -> list[dict]: ...

    async def list_violations(self, user_id: int, *, limit: int = 50) -> list[dict]: ...

    async def create_snapshot(self, user_id: int, payload: dict) -> dict: ...
