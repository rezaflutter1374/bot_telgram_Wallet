from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from domain.enums import SettlementMode, SettlementStatus


class SettlementStatusDTO(BaseModel):
    batch_key: str
    mode: SettlementMode
    status: SettlementStatus
    last_checkpoint: str | None = None
    error_message: str | None = None
    target_date: datetime
    created_at: datetime
    completed_at: datetime | None = None


class SettlementSummaryDTO(BaseModel):
    settlement_id: int | None = None
    batch_key: str
    mode: SettlementMode
    status: SettlementStatus
    target_date: datetime
    price_usd: Decimal | None = None
    price_source: str | None = None
    affected_users: int = 0
    net_pnl_usd: Decimal = Decimal("0")
    report_json: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class SettlementResultDTO(BaseModel):
    status: SettlementStatus
    idempotent: bool = False
    summary: SettlementSummaryDTO


class SettlementHistoryItemDTO(SettlementSummaryDTO):
    replay_of_settlement_id: int | None = None
    rollback_of_settlement_id: int | None = None
