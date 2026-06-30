from __future__ import annotations

from datetime import datetime
from typing import Protocol


class SettlementEngine(Protocol):
    async def execute(
        self,
        *,
        mode: str,
        settlement_at: datetime | None = None,
        actor_user_id: int | None = None,
        user_ids: list[int] | None = None,
        idempotency_key: str | None = None,
        replay_of_settlement_id: int | None = None,
    ) -> dict: ...

    async def rollback(self, *, settlement_id: int, actor_user_id: int | None = None, reason: str | None = None) -> dict: ...

    async def replay(self, *, settlement_id: int, actor_user_id: int | None = None, idempotency_key: str | None = None) -> dict: ...

    async def list_history(self, *, limit: int = 20) -> list[dict]: ...

    async def get_status(self, *, batch_key: str) -> dict | None: ...
