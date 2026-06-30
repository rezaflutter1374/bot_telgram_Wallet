from __future__ import annotations

from typing import Protocol

from domain.enums import TicketPriority, TicketStatus


class TicketRepo(Protocol):
    async def create_ticket(self, user_id: int, subject: str, priority: TicketPriority) -> dict: ...

    async def get(self, ticket_id: int) -> dict | None: ...

    async def add_message(
        self,
        ticket_id: int,
        author_user_id: int | None,
        author_role: str,
        message: str,
        attachment_file_ids_enc: list[str],
    ) -> dict: ...

    async def set_status(self, ticket_id: int, status: TicketStatus) -> dict: ...

    async def list_tickets(
        self,
        *,
        user_id: int | None = None,
        status: TicketStatus | None = None,
        query: str | None = None,
        limit: int = 20,
    ) -> list[dict]: ...
