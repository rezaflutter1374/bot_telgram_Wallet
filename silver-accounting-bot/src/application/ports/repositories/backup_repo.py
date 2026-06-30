from __future__ import annotations

from typing import Protocol


class BackupRepo(Protocol):
    async def create_snapshot(self) -> dict: ...

    async def restore_snapshot(self, snapshot: dict, *, wipe_existing: bool = True) -> None: ...

