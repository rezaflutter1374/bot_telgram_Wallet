from __future__ import annotations

from typing import Protocol


class DeadLetterRepo(Protocol):
    async def list_entries(self, limit: int = 50, source: str | None = None) -> list[dict]: ...

    async def count_by_source(self) -> dict[str, int]: ...
