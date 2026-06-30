from __future__ import annotations

from typing import Protocol


class CleanupRepo(Protocol):
    async def purge_old_records(self, retention_days: int) -> dict: ...
