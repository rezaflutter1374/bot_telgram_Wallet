from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol


class LedgerRepo(Protocol):
    async def post_entry(
        self,
        reference: str,
        description: str,
        entry_type: str,
        lines: list[dict],
        created_by_user_id: int | None = None,
        posted_at: datetime | None = None,
        correlation_id: str | None = None,
    ) -> dict: ...

    async def get_entry(self, entry_id: int) -> dict | None: ...

    async def get_entry_by_reference(self, reference: str) -> dict | None: ...

    async def list_entries(
        self,
        *,
        entry_type: str | None = None,
        user_id: int | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]: ...

    async def account_balance(
        self,
        account_code: str,
        at_dt: datetime | None = None,
    ) -> Decimal: ...

    async def list_accounts(self) -> list[dict]: ...

    async def ensure_accounts(self, accounts: list[dict]) -> None: ...
