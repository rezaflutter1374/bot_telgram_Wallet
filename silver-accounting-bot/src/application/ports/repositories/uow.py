from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol


class UnitOfWork(Protocol):
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]: ...

