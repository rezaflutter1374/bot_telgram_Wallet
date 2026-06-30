from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from domain.enums import ExecutionType, OrderCancellationStatus, OrderSide, OrderStatus, OrderTimeInForce, OrderType


class OrderRepo(Protocol):
    async def create_order(
        self,
        user_id: int,
        side: OrderSide,
        order_type: OrderType,
        time_in_force: OrderTimeInForce,
        quantity_kg: Decimal,
        quoted_price: Decimal,
        limit_price: Decimal | None,
        stop_price: Decimal | None,
        reserved_balance_usd: Decimal,
        reserved_margin_usd: Decimal,
        post_only: bool,
        reduce_only: bool,
        client_order_id: str | None,
        idempotency_key: str | None,
        quote_expires_at: datetime,
    ) -> dict: ...

    async def get(self, order_id: int) -> dict | None: ...

    async def list_for_user(self, user_id: int, limit: int = 20) -> list[dict]: ...

    async def attach_receipt(
        self,
        order_id: int,
        receipt_file_id_enc: str,
        status: OrderStatus,
    ) -> dict: ...

    async def set_status(self, order_id: int, status: OrderStatus) -> dict: ...

    async def get_by_idempotency_key(self, idempotency_key: str) -> dict | None: ...

    async def list_open_orders(
        self,
        *,
        side: OrderSide | None = None,
        limit: int = 100,
    ) -> list[dict]: ...

    async def list_triggerable_orders(self, current_price: Decimal, *, limit: int = 100) -> list[dict]: ...

    async def list_expired_orders(self, as_of: datetime, *, limit: int = 100) -> list[dict]: ...

    async def mark_triggered(self, order_id: int) -> dict: ...

    async def apply_fill(
        self,
        *,
        order_id: int,
        filled_quantity_kg: Decimal,
        fill_price_usd: Decimal,
        fee_usd: Decimal,
        slippage_bps: Decimal,
        status: OrderStatus,
        executed_at: datetime,
    ) -> dict: ...

    async def release_reservations(self, order_id: int) -> dict: ...

    async def create_trade(
        self,
        *,
        maker_order_id: int,
        taker_order_id: int,
        buy_order_id: int,
        sell_order_id: int,
        match_key: str,
        price_usd: Decimal,
        quantity_kg: Decimal,
        buy_fee_usd: Decimal,
        sell_fee_usd: Decimal,
        slippage_bps: Decimal,
        payload: dict,
        executed_at: datetime,
    ) -> dict: ...

    async def add_execution_report(
        self,
        *,
        order_id: int,
        execution_type: ExecutionType,
        status: OrderStatus,
        quantity_kg: Decimal,
        price_usd: Decimal,
        fee_usd: Decimal,
        payload: dict,
        trade_id: int | None = None,
    ) -> dict: ...

    async def list_execution_reports(self, order_id: int, limit: int = 100) -> list[dict]: ...

    async def list_trade_history(
        self,
        *,
        user_id: int | None = None,
        limit: int = 100,
    ) -> list[dict]: ...

    async def get_cancellation(self, order_id: int) -> dict | None: ...

    async def request_cancellation(self, order_id: int, requested_by_user_id: int) -> dict: ...

    async def set_cancellation_status(self, order_id: int, status: OrderCancellationStatus) -> dict: ...

    async def list_pending_cancellations(self, limit: int = 50) -> list[dict]: ...

    async def get_trade(self, trade_id: int) -> dict | None: ...
