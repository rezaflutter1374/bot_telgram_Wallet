from __future__ import annotations

from typing import Protocol

from domain.enums import NotificationStatus


class NotificationRepo(Protocol):
    async def enqueue(self, user_id: int, kind: str, payload: dict, channel: str = "telegram") -> dict: ...

    async def list_pending(self, limit: int = 100) -> list[dict]: ...

    async def mark(self, notification_id: int, status: NotificationStatus, error: str | None = None) -> None: ...

