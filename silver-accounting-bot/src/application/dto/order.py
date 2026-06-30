from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel

from domain.enums import OrderSide, OrderStatus, OrderTimeInForce, OrderType


class OrderDTO(BaseModel):
    id: int
    user_id: int
    side: OrderSide
    order_type: OrderType
    time_in_force: OrderTimeInForce
    quantity_kg: Decimal
    remaining_quantity_kg: Decimal
    filled_quantity_kg: Decimal
    quoted_price: Decimal
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    average_fill_price_usd: Decimal = Decimal("0")
    notional_value_usd: Decimal = Decimal("0")
    reserved_balance_usd: Decimal = Decimal("0")
    reserved_margin_usd: Decimal = Decimal("0")
    executed_fee_usd: Decimal = Decimal("0")
    slippage_bps: Decimal = Decimal("0")
    post_only: bool = False
    reduce_only: bool = False
    is_triggered: bool = False
    client_order_id: str | None = None
    idempotency_key: str | None = None
    quote_expires_at: datetime
    status: OrderStatus
    created_at: datetime
    updated_at: datetime
    executed_at: datetime | None = None
    cancelled_at: datetime | None = None
