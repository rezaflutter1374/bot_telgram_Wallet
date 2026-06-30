from __future__ import annotations

from typing import Protocol


class CircuitBreakerRepo(Protocol):
    async def get_state(self, name: str) -> dict | None: ...

    async def reset(self, name: str) -> None: ...

    async def all_states(self) -> list[dict]: ...
