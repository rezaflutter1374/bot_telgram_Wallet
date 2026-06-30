from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel


class PriceDTO(BaseModel):
    source: str = "manual_admin"
    buy_price: Decimal
    sell_price: Decimal
    spread: Decimal
    commission: Decimal
    premium: Decimal
    discount: Decimal
    is_verified: bool = True
    is_stale: bool = False
    updated_at: datetime
