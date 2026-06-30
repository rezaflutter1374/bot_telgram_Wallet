from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel

from domain.enums import TicketPriority, TicketStatus


class TicketDTO(BaseModel):
    id: int
    user_id: int
    subject: str
    priority: TicketPriority
    status: TicketStatus
    created_at: datetime

