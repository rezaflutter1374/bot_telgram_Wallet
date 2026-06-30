from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel

from domain.enums import PaymentStatus, PaymentType


class PaymentDTO(BaseModel):
    id: int
    user_id: int
    payment_type: PaymentType
    amount_usd: Decimal
    status: PaymentStatus
    created_at: datetime

