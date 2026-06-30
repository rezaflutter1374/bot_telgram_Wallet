from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from domain.enums import JournalAccountType


class AccountingRepo(Protocol):
    async def ensure_default_chart(self) -> None: ...

    async def create_account(self, code: str, name: str, account_type: JournalAccountType, parent_code: str | None) -> dict: ...

    async def get_account_by_code(self, code: str) -> dict | None: ...

    async def create_bank_account(self, name: str, account_number_enc: str) -> dict: ...

    async def list_bank_accounts(self, only_active: bool = True) -> list[dict]: ...

    async def create_payment_card(self, bank_account_id: int, label: str, card_number_enc: str) -> dict: ...

    async def list_payment_cards(self, bank_account_id: int | None = None, only_active: bool = True) -> list[dict]: ...

    async def post_journal_entry(
        self,
        reference: str | None,
        description: str,
        posted_at: datetime,
        created_by_user_id: int | None,
        lines: list[dict],
    ) -> dict: ...

    async def trial_balance(self, from_dt: datetime | None, to_dt: datetime | None) -> list[dict]: ...

    async def profit_and_loss(self, from_dt: datetime | None, to_dt: datetime | None) -> dict: ...

    async def balance_sheet(self, at_dt: datetime | None) -> dict: ...

    async def cash_flow(self, from_dt: datetime | None, to_dt: datetime | None) -> dict: ...

    async def financial_dashboard(self, from_dt: datetime | None, to_dt: datetime | None) -> dict: ...

    async def close_period(
        self,
        period_type: str,
        label: str,
        start_date: datetime,
        end_date: datetime,
        closed_by_user_id: int,
    ) -> dict: ...

    async def list_periods(self, period_type: str | None = None, limit: int = 20) -> list[dict]: ...

    async def reopen_period(self, period_id: int, reopened_by_user_id: int) -> dict: ...
