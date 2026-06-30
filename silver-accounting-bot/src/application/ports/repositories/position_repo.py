from __future__ import annotations

from decimal import Decimal
from typing import Protocol


class PositionRepo(Protocol):
    async def get_net_kg(self, user_id: int) -> Decimal: ...

    async def adjust_net_kg(self, user_id: int, delta_kg: Decimal, avg_price_usd: Decimal) -> None: ...

    async def get_position(self, user_id: int) -> dict: ...

    async def apply_trade(
        self,
        *,
        user_id: int,
        side: str,
        quantity_kg: Decimal,
        price_usd: Decimal,
    ) -> dict: ...
