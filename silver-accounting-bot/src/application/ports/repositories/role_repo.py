from __future__ import annotations

from typing import Protocol


class RoleRepo(Protocol):
    async def ensure_defaults(self) -> None: ...

    async def user_has_permission(self, user_id: int, permission: str) -> bool: ...

    async def grant_role(self, user_id: int, role: str) -> None: ...

    async def get_user_roles(self, user_id: int) -> set[str]: ...

