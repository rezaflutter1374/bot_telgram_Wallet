from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any


class ArbitrationReason(str, Enum):
    price_correction = "price_correction"
    trade_reversal = "trade_reversal"
    settlement_adjustment = "settlement_adjustment"
    supervisor_override = "supervisor_override"
    system_error = "system_error"


class ArbitrationStatus(str, Enum):
    approved = "approved"
    rejected = "rejected"
    pending_review = "pending_review"


@dataclass(frozen=True)
class ArbitrationResult:
    arbitration_id: int
    order_id: int | None
    trade_id: int | None
    reason: ArbitrationReason
    old_price_usd: Decimal | None
    new_price_usd: Decimal | None
    adjustment_usd: Decimal
    status: ArbitrationStatus
    actor_user_id: int
    notes: str | None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ArbitrationHandler:
    def compute_adjustment(
        self,
        *,
        reason: ArbitrationReason,
        old_price_usd: Decimal | None = None,
        new_price_usd: Decimal | None = None,
        quantity_kg: Decimal | None = None,
        old_pnl_usd: Decimal | None = None,
        new_pnl_usd: Decimal | None = None,
    ) -> Decimal:
        if reason in {ArbitrationReason.supervisor_override, ArbitrationReason.system_error}:
            return Decimal("0")

        if old_pnl_usd is not None and new_pnl_usd is not None:
            return (new_pnl_usd - old_pnl_usd).quantize(Decimal("0.01"))

        if old_price_usd is not None and new_price_usd is not None and quantity_kg is not None and quantity_kg > 0:
            return ((new_price_usd - old_price_usd) * quantity_kg).quantize(Decimal("0.01"))

        return Decimal("0")

    def validate_arbitration_request(
        self,
        reason: ArbitrationReason,
        old_price_usd: Decimal | None,
        new_price_usd: Decimal | None,
        notes: str | None,
    ) -> tuple[bool, str | None]:
        if not notes or len(notes.strip()) < 10:
            return False, "Arbitration requires detailed notes (min 10 chars)"
        if reason == ArbitrationReason.price_correction:
            if old_price_usd is None or new_price_usd is None:
                return False, "Price correction requires both old and new prices"
        return True, None
