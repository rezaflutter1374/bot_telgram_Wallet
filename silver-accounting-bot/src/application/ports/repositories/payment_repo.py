from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from domain.enums import PaymentStatus, PaymentType


class PaymentReconciliationRepo(Protocol):
    async def find_duplicate(
        self,
        user_id: int,
        amount_usd: Decimal,
        receipt_hash: str,
        window_hours: int = 24,
    ) -> dict | None: ...

    async def find_by_reference(self, reference_number: str) -> dict | None: ...

    async def record(
        self,
        payment_request_id: int,
        *,
        reference_number: str | None = None,
        duplicate_check_hash: str | None = None,
        is_duplicate: bool = False,
        matched_payment_request_id: int | None = None,
    ) -> dict: ...


class PaymentRepo(Protocol):
    async def create_request(
        self,
        user_id: int,
        payment_type: PaymentType,
        amount_usd: Decimal,
        receipt_file_ids_enc: list[str],
        bank_account_id: int | None,
    ) -> dict: ...

    async def get(self, payment_id: int) -> dict | None: ...

    async def list_for_user(self, user_id: int, limit: int = 20) -> list[dict]: ...

    async def list_pending(self, limit: int = 50) -> list[dict]: ...

    async def set_status(
        self,
        payment_id: int,
        status: PaymentStatus,
        reviewer_user_id: int | None,
        review_note: str | None,
    ) -> dict: ...

    async def reconcile(
        self,
        payment_id: int,
        reference_number: str | None = None,
        reconciled_by_user_id: int | None = None,
    ) -> dict: ...

