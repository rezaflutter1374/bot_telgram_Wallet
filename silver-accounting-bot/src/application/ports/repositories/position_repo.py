from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol


class PositionRepo(Protocol):
    async def get_net_kg(self, user_id: int) -> Decimal: ...

    async def adjust_net_kg(
        self,
        user_id: int,
        delta_kg: Decimal,
        avg_price_usd: Decimal,
    ) -> None: ...

    async def get_position(self, user_id: int) -> dict: ...

    async def apply_trade(
        self,
        *,
        user_id: int,
        side: str,
        quantity_kg: Decimal,
        price_usd: Decimal,
        fee_usd: Decimal = Decimal("0"),
    ) -> dict: ...

    async def update_position(
        self,
        user_id: int,
        *,
        net_kg: Decimal,
        avg_price_usd: Decimal,
        realized_pnl_usd: Decimal,
    ) -> None: ...

    async def list_positions(
        self,
        *,
        min_abs_net_kg: Decimal | None = None,
        limit: int = 100,
    ) -> list[dict]: ...

    async def get_position_history(
        self,
        user_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]: ...
