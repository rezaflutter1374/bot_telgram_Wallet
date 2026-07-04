from __future__ import annotations

from datetime import datetime
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

    async def add_event(
        self,
        actor_user_id: int | None,
        action: str,
        entity_type: str,
        entity_id: str,
        *,
        before: dict | None = None,
        after: dict | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        ip_address: str | None = None,
        metadata: dict | None = None,
        reason: str | None = None,
    ) -> dict: ...

    async def get_chain(
        self,
        entity_type: str,
        entity_id: str,
    ) -> list[dict]: ...

    async def verify_chain(
        self,
        entity_type: str,
        entity_id: str,
    ) -> bool: ...

    async def search_audit(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        event_type: str | None = None,
        entity_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict]: ...
