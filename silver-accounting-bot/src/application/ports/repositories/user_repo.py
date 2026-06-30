from __future__ import annotations

from typing import Protocol

from domain.enums import KycStatus


class UserRepo(Protocol):
    async def get_by_telegram_id(self, telegram_id: int) -> dict | None: ...

    async def get(self, user_id: int) -> dict | None: ...

    async def list_users(
        self,
        *,
        role: str | None = None,
        kyc_status: KycStatus | None = None,
        language_code: str | None = None,
        trading_active: bool | None = None,
        limit: int = 1000,
    ) -> list[dict]: ...

    async def create_user(
        self,
        telegram_id: int,
        full_name: str | None,
        phone_number: str | None,
        kyc_status: KycStatus,
        language_code: str | None = None,
    ) -> dict: ...

    async def update_kyc(
        self,
        user_id: int,
        full_name: str | None,
        phone_number: str | None,
        national_id_enc: str | None,
        passport_file_id_enc: str | None,
        selfie_file_id_enc: str | None,
        verification_docs_file_ids_enc: list[str],
        kyc_status: KycStatus,
    ) -> dict: ...

    async def set_kyc_status(self, user_id: int, kyc_status: KycStatus) -> dict: ...

    async def set_language_code(self, user_id: int, language_code: str | None) -> dict: ...
