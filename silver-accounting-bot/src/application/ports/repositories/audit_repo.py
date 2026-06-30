from __future__ import annotations

from typing import Protocol


class AuditRepo(Protocol):
    async def add(
        self,
        actor_user_id: int | None,
        event_type: str,
        entity_type: str | None,
        entity_id: str | None,
        payload: dict,
    ) -> None: ...

    async def list_events(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        event_type: str | None = None,
        entity_type: str | None = None,
    ) -> list[dict]: ...

