from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware

from core.di import Container


class ContainerMiddleware(BaseMiddleware):
    def __init__(self, container: Container) -> None:
        self._container = container

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        data["container"] = self._container
        data["services"] = self._container.services
        data["encryptor"] = self._container.encryptor
        return await handler(event, data)

