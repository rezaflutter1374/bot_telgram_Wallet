from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel

from domain.enums import KycStatus


class UserDTO(BaseModel):
    id: int
    telegram_id: int
    full_name: str | None
    phone_number: str | None
    language_code: str | None = None
    kyc_status: KycStatus
    created_at: datetime
