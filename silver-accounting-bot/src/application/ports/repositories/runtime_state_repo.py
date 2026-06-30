from __future__ import annotations

from typing import Protocol


class RuntimeStateRepo(Protocol):
    async def get_maintenance_mode(self) -> dict: ...

    async def set_maintenance_mode(self, enabled: bool, message: str | None, actor_user_id: int | None) -> dict: ...
